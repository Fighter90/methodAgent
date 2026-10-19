"""Нормативная база знаний: выжимки НПА, ФГОС и методических рекомендаций из открытых официальных источников.

Файлы registry/norms/*.md (в образе, только для чтения) с заголовком YAML: id, title, source, url,
applies (типы программ), keywords, checked_at. Поиск по словам детерминирован и не тратит бюджет шлюза;
найденные фрагменты агент передаёт навыкам каркаса и комплекта и ссылается на акт в нормативной базе.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from app.kb.orgdocs import chunks
from app.kb.registry import REGISTRY_DIR, _kw_hit

NORMS_DIR = REGISTRY_DIR / 'norms'


def _words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r'[a-zа-яё0-9]{4,}', text.lower())}


@lru_cache
def norms() -> list[dict[str, Any]]:
    out = []
    for md in sorted(NORMS_DIR.glob('*.md')):
        raw = md.read_text(encoding='utf-8')
        meta: dict[str, Any] = {}
        body = raw
        if raw.startswith('---'):
            _, front, body = raw.split('---', 2)
            meta = yaml.safe_load(front) or {}
        parts = chunks(body.strip())
        out.append({
            'id': meta.get('id', md.stem), 'title': meta.get('title', md.stem), 'source': meta.get('source', ''),
            'url': meta.get('url', ''), 'applies': meta.get('applies', []), 'keywords': meta.get('keywords', []),
            'npa_id': meta.get('npa_id') or '', 'checked_at': str(meta.get('checked_at', '')), 'chars': len(body),
            'chunks': [{'i': i, 'text': t, 'words': _words(t)} for i, t in enumerate(parts)],
        })
    return out


def public(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k != 'chunks'} | {'chunks': len(item['chunks'])}


def search(query: str, program_type: str = '', k: int = 4) -> list[dict[str, Any]]:
    """Лучшие фрагменты: доля общих слов с запросом плюс бонус за ключевые слова акта и тип программы."""
    from app.kb.abbr import expand

    query = expand(query)  # «педагог ДО» → и «дополнительное образование детей»
    low = query.lower()
    qw = _words(query)
    scored = []
    for d in norms():
        if program_type and d['applies'] and program_type not in d['applies']:
            continue
        bonus = 0.15 * sum(1 for kw in d['keywords'] if _kw_hit(str(kw), low))
        for c in d['chunks']:
            score = len(qw & c['words']) / (len(qw) or 1) + bonus
            scored.append((score, d, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for s, d, c in scored:
        if s <= 0.05 or (d['id'], c['i']) in seen:
            continue
        seen.add((d['id'], c['i']))
        out.append({'doc_id': d['id'], 'name': d['title'], 'source': d['source'], 'url': d['url'], 'npa_id': d['npa_id'],
                    'kind': 'norm', 'chunk': c['i'], 'score': round(s, 3), 'text': c['text'][:700]})
        if len(out) >= k:
            break
    return out
