"""Реестр ПС, НПА, версий инструментов и литературы (FR-10).

Агент берёт коды и реквизиты только отсюда; всё, чего нет в реестре,
попадает в программу с пометкой «не подтверждено».
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR
from app.programs.schemas import ProfStandard, ProgramType, Source, TrudFunction

REGISTRY_DIR = ROOT_DIR / 'registry'


REGISTRY_FILES = {'npa': 'npa.json', 'ps': 'profstandards.json', 'tools': 'tools.json', 'literature': 'literature.json', 'org': 'org_profile.json'}


def override_dir() -> Path:
    """Правки администратора (PUT /org/profile, /org/registry) лежат в data_dir: образ контейнера только для чтения."""
    from app.core.config import get_settings

    return get_settings().data_dir / 'registry'


def _load(name: str) -> Any:
    own = override_dir() / name
    path = own if own.exists() else REGISTRY_DIR / name
    return json.loads(path.read_text(encoding='utf-8'))


def save_override(kind: str, data: Any) -> None:
    """Записывает раздел реестра или профиль организации и сбрасывает кэш."""
    d = override_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / REGISTRY_FILES[kind]).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    registry.cache_clear()


# Нормативная база из открытых источников (НПА, профстандарты, ФГОС): дополняет основные реестры по id или коду
EXTRA_FILES = {'npa': 'kb_npa.json', 'ps': 'kb_profstandards.json', 'fgos': 'kb_fgos.json', 'literature': 'kb_literature.json'}
_REPEALED = ('утратил', 'repealed', 'отмен', 'не действует')


def _key(kind: str, item: dict[str, Any]) -> str:
    return str(item.get('code') if kind in ('ps', 'fgos') else item.get('id') or item.get('bibl'))


def _in_force(item: dict[str, Any]) -> bool:
    return not any(w in str(item.get('status', '')).lower() for w in _REPEALED)


def _merge(kind: str, base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Записи из базы источников заменяют одноимённые (у них свежая проверка), утратившие силу отбрасываются."""
    out = {_key(kind, i): i for i in base}
    for item in extra:
        k = _key(kind, item)
        if not _in_force(item):
            out.pop(k, None)
            continue
        if kind == 'ps':
            item.setdefault('keywords', [])
            item.setdefault('tf', [])
        if kind == 'npa':
            item.setdefault('applies', [])
            item.setdefault('url', '')
        out[k] = {**out.get(k, {}), **item}
    return list(out.values())


@lru_cache
def registry() -> dict[str, Any]:
    data = {kind: _load(name) for kind, name in REGISTRY_FILES.items()}
    data['fgos'] = []
    for kind, name in EXTRA_FILES.items():
        if (override_dir() / name).exists() or (REGISTRY_DIR / name).exists():
            data[kind] = _merge(kind, data.get(kind, []), _load(name))
    return data


def _stems_hit(keywords: list[str], low: str) -> bool:
    return any((re.search(rf'\b{re.escape(k)}', low) if len(k) <= 3 else k in low) for k in keywords)


def norm_base_for(program_type: ProgramType, text: str = '') -> list[Source]:
    """Обязательные акты типа программы (273-ФЗ + № 499 для ДПП, 273-ФЗ + № 629 для ДООП, FR-07)
    и акты, которые подходят к запросу по ключевым словам (ДОТ, дети, практика, персональные данные)."""
    low = text.lower()
    out = []
    for item in registry()['npa']:
        if program_type.value not in item.get('applies', []) or not _in_force(item):
            continue
        core = item.get('core', 'keywords' not in item)
        if core or (low and _stems_hit(item.get('keywords', []), low)):
            out.append(
                Source(id=item['id'], kind='law', bibl=item['bibl'], url=item.get('url', ''), confirmed=True, checked_at=item.get('checked_at', ''))
            )
    return out


def find_ps(code: str) -> dict[str, Any] | None:
    return next((p for p in registry()['ps'] if p['code'] == code), None)


def pick_ps(text: str, hint: str = '') -> ProfStandard | None:
    """Подбирает ПС по ключевым словам направления; кандидат всегда из реестра."""
    if hint:
        found = find_ps(hint)
        if found:
            return to_ps(found)
    low = text.lower()
    best, best_score = None, 0
    for ps in registry()['ps']:
        score = sum(1 for kw in ps['keywords'] if kw in low)
        if score > best_score:
            best, best_score = ps, score
    return to_ps(best) if best else None


def to_ps(item: dict[str, Any]) -> ProfStandard:
    return ProfStandard(
        code=item['code'],
        title=item['title'],
        order=item['order'],
        confirmed=bool(item.get('tf_verified', False)),
        tf=[TrudFunction(**tf) for tf in item['tf']],
    )


def tf_codes(code: str) -> set[str]:
    ps = find_ps(code)
    return {tf['code'] for tf in ps['tf']} if ps else set()


def for_school(item: dict[str, Any]) -> bool:
    """Источник годится для школьной программы: книга для детей или официальная документация."""
    return item['kind'] == 'url' or any(t in ('школ', 'дет') for t in item.get('tags', []))


def literature_for(text: str, limit: int = 6, school: bool = False) -> list[Source]:
    low = text.lower()
    scored = []
    for item in registry()['literature']:
        if school and not for_school(item):
            continue
        score = sum(1 for t in item['tags'] if (re.search(rf'\b{re.escape(t)}\b', low) if len(t) <= 3 else t in low))
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [
        Source(id=i['id'], kind=i['kind'], bibl=i['bibl'], url=i.get('url', ''), confirmed=True, checked_at=i.get('checked_at', ''))
        for _, i in scored[:limit]
    ]


def _domain(url: str) -> str:
    m = re.search(r'https?://(?:www\.)?([^/\s]+)', url) or re.search(r'\b((?:[a-z0-9-]+\.)+(?:io|org|com|ru|dev|net))\b', url.lower())
    return m.group(1).lower().removeprefix('www.') if m else ''


def _site(host: str) -> str:
    """Регистрируемый домен: docs.python.org и python.org — один сайт."""
    return '.'.join(host.split('.')[-2:]) if host else ''


_GENERIC = {'документация', 'documentation', 'docs', 'русский', 'перевод', 'project', 'hashicorp', 'format', 'guide', 'reference', 'manual', 'официальная'}

_DOC_WORDS = ('документац', 'documentation', 'docs', 'руководство', 'официальн', 'reference', 'manual')


def match_source(bibl: str) -> dict[str, Any] | None:
    """Ищет источник в реестре: по сайту ссылки, по «документации <инструмента>», затем по значимым словам."""
    words = {w for w in _norm(bibl).split() if len(w) > 3}
    if not words:
        return None
    low = bibl.lower()
    site = _site(_domain(bibl))
    if site:
        for item in registry()['literature']:
            if item.get('url') and _site(_domain(item['url'])) == site:
                return item
    if any(k in low for k in _DOC_WORDS):
        for item in registry()['literature']:
            if item['kind'] != 'url':
                continue
            names = {w for w in _norm(item['bibl']).split() if len(w) > 3} - _GENERIC
            if names and names & words:
                return item
    for item in registry()['literature'] + registry()['npa']:
        ref = {w for w in _norm(item['bibl']).split() if len(w) > 3}
        if ref and len(words & ref) / len(ref) >= 0.6:
            return item
        surname = _norm(item['bibl']).split()[0] if item['kind'] == 'book' else ''
        if surname in words and len(words & ref) >= 2:
            return item
    return None


def _norm(text: str) -> str:
    return ''.join(ch.lower() if ch.isalnum() else ' ' for ch in text)


def tools() -> dict[str, Any]:
    return registry()['tools']


def registry_path() -> Path:
    return REGISTRY_DIR


def org_profile() -> dict[str, Any]:
    return registry()['org']
