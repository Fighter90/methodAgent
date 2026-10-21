"""Распознавание инструментов, версий, устаревших конструкций и сервисов (FR-61, SPEC-KB-21).

Переиспользуемый слой над реестром `registry/tools.json`: один и тот же сканер обслуживает
правило V-23, актуализацию и песочницу; реестр передаётся параметром, поэтому переопределения
администратора (`PUT /org/registry`) и тесты подставляют свой вариант без правки кода.
Перед сопоставлением текст нормализуется: регистр, «ё → е», повторы букв, смешение
латиницы и кириллицы («PоstgreS», «питоон») — меткие опечатки не прячут находку.
"""

from __future__ import annotations

import re

from app.kb.registry import tools

# Гомоглифы латиницы и кириллицы, которые чаще всего путают при наборе (MET-9, шаг 2)
_LAT2CYR = str.maketrans({'e': 'е', 'a': 'а', 'o': 'о', 'c': 'с', 'p': 'р', 'x': 'х'})
_CYR2LAT = str.maketrans({'е': 'e', 'а': 'a', 'о': 'o', 'с': 'c', 'р': 'p', 'х': 'x'})
_WORD = re.compile(r'[a-zа-яё]+')
_CYR_ONLY = re.compile(r'[а-яё]+\Z')


def tool_patterns(reg: dict) -> dict[str, str]:
    """Регулярное выражение на инструмент из его алиасов: сначала самые длинные, чтобы «python3» не съелся «python»."""
    out: dict[str, str] = {}
    for tool, aliases in (reg.get('aliases') or {}).items():
        # реестр редактируется администратором: кривой тип не должен ломать распознавание
        alts = sorted({str(a).lower() for a in aliases if isinstance(a, str)}, key=len, reverse=True) if isinstance(aliases, list) else []
        if alts:
            out[tool] = '|'.join(re.escape(a) for a in alts)
    return out


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r'\d+', v)[:3])


def _reshape(low: str, *, dedup: bool, to_cyr: bool) -> str:
    """Слова с повторами букв и смешанным алфавитом приводятся к каноническому написанию.

    Повторы схлопываются только в кириллических словах длиннее 4 букв, чтобы не ломать
    легитимные слова: «класссс» → «класс» (3+ одинаковых подряд), при `dedup` — и сдвоенные
    («питоон» → «питон»). Слова, где намешаны латиница и кириллица, приводятся к одному
    алфавиту через гомоглифы: «PоstgreS» → «postgres», «пoстгрес» → «постгрес».
    """
    table = _LAT2CYR if to_cyr else _CYR2LAT

    def _fix(m: re.Match[str]) -> str:
        w = m.group(0)
        if re.search(r'[a-z]', w) and re.search(r'[а-яё]', w):
            w = w.translate(table)
        if _CYR_ONLY.fullmatch(w) and len(w) > 4:
            w = re.sub(r'(.)\1+', r'\1', w) if dedup else re.sub(r'(.)\1{2,}', r'\1\1', w)
        return w

    return _WORD.sub(_fix, low)


def _variants(text: str) -> list[str]:
    """Варианты текста для сопоставления: исходный плюс исправленные, без повторов."""
    low = text.lower().replace('ё', 'е')
    out, seen = [low], {low}
    for dedup in (False, True):
        for to_cyr in (True, False):
            v = _reshape(low, dedup=dedup, to_cyr=to_cyr)
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


def scan_tools(text: str, reg: dict | None = None) -> list[dict[str, str]]:
    """Устаревшие конструкции, версии ниже поддерживаемых, недоступные в России сервисы, старые источники.

    Текст сопоставляется в нескольких нормализованных вариантах, находки сливаются без дубликатов.
    """
    reg = tools() if reg is None else reg
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(kind: str, found: str, message: str, replacement: str) -> None:
        key = f'{kind}:{found.lower()}'
        if key not in seen:
            seen.add(key)
            out.append({'kind': kind, 'found': found, 'message': message, 'replacement': replacement})

    repl = reg.get('outdated_replacements', {})
    current, minimum = reg['current'], reg.get('min_supported', {})
    patterns = tool_patterns(reg)
    for v in _variants(text):
        for key, msg in reg['outdated'].items():
            if key in v:
                _add('construct', key, msg, repl.get(key, ''))
        for tool, pattern in patterns.items():
            for m in re.finditer(rf'\b(?:{pattern})\s*v?(\d+(?:\.\d+)?)\b', v):
                ver = m.group(1)
                if tool not in current or (tool == 'python' and _ver(ver)[0] < 2):
                    continue
                if tool in minimum and _ver(ver) < _ver(minimum[tool]):
                    _add('version', m.group(0), f'{tool} {ver} снят с поддержки (минимум {minimum[tool]})', f'{tool} {current[tool]}')
                elif _ver(ver)[:1] < _ver(current[tool])[:1] or (_ver(ver) < _ver(current[tool]) and tool in ('python', 'pandas', 'postgresql', 'kubernetes')):
                    _add('update', m.group(0), f'Есть более новая версия {tool}: {current[tool]}', f'{tool} {current[tool]}')
        for svc in reg.get('ai_services_blocked', []):
            if re.search(rf'\b{re.escape(svc.lower())}\b', v):
                _add('service', svc, f'{svc} недоступен в России без ограничений', 'GigaChat или YandexGPT (Алиса)')
    for y in re.findall(r'\b(19[5-9]\d|200\d|201[0-5])\b(?=\s*\.?\s*[–—-]?\s*\d*\s*с\.)', text):
        _add('source', y, f'Источник {y} года старше 10 лет', 'издание не старше 2016 года из реестра литературы')
    return out
