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


def _load(name: str) -> Any:
    return json.loads((REGISTRY_DIR / name).read_text(encoding='utf-8'))


@lru_cache
def registry() -> dict[str, Any]:
    return {
        'npa': _load('npa.json'),
        'ps': _load('profstandards.json'),
        'tools': _load('tools.json'),
        'literature': _load('literature.json'),
        'org': _load('org_profile.json'),
    }


def norm_base_for(program_type: ProgramType) -> list[Source]:
    """273-ФЗ + № 499 для ДПП ПК, 273-ФЗ + № 629 для ДООП (FR-07)."""
    out = []
    for item in registry()['npa']:
        if program_type.value in item['applies']:
            out.append(
                Source(id=item['id'], kind='law', bibl=item['bibl'], url=item['url'], confirmed=True, checked_at=item['checked_at'])
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


def literature_for(text: str, limit: int = 6) -> list[Source]:
    low = text.lower()
    scored = []
    for item in registry()['literature']:
        score = sum(1 for t in item['tags'] if t in low)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda x: -x[0])
    return [
        Source(id=i['id'], kind=i['kind'], bibl=i['bibl'], url=i.get('url', ''), confirmed=True, checked_at='2026-10-17')
        for _, i in scored[:limit]
    ]


def _domain(url: str) -> str:
    m = re.search(r'https?://(?:www\.)?([^/\s]+)', url) or re.search(r'\b((?:[a-z0-9-]+\.)+(?:io|org|com|ru|dev|net))\b', url.lower())
    return m.group(1).lower().removeprefix('www.') if m else ''


def _site(host: str) -> str:
    """Регистрируемый домен: docs.python.org и python.org — один сайт."""
    return '.'.join(host.split('.')[-2:]) if host else ''


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
            names = {w for w in _norm(item['bibl']).split() if len(w) > 3} - {'документация', 'documentation', 'русский', 'перевод', 'project', 'hashicorp'}
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
