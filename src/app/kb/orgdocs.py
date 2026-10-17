"""База знаний организации (FR-09): шаблоны, положения и иные документы АЦР.

Администратор загружает документ — текст режется на фрагменты и индексируется
эмбеддингами шлюза (Giga-Embeddings). Без модели поиск идёт по пересечению слов.
Найденные фрагменты попадают в программу со ссылкой на документ-источник.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from typing import Any

from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import NotFound
from app.kb.files import parse_reference

logger = logging.getLogger(__name__)

KINDS = {'template': 'Шаблон программы', 'regulation': 'Положение', 'other': 'Иной документ'}
_CHUNK = 900
_MAX_CHUNKS = 200
_lock = threading.Lock()


def _path():
    d = get_settings().data_dir / 'kb'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'index.json'


def _load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {'docs': []}
    return json.loads(p.read_text(encoding='utf-8'))


def _save(data: dict[str, Any]) -> None:
    p = _path()
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)


def chunks(text: str) -> list[str]:
    """Фрагменты по абзацам, не длиннее _CHUNK символов."""
    out, buf = [], ''
    for para in (x.strip() for x in re.split(r'\n\s*\n|\n', text)):
        if not para:
            continue
        if buf and len(buf) + len(para) > _CHUNK:
            out.append(buf)
            buf = ''
        buf = f'{buf}\n{para}'.strip() if buf else para[: _CHUNK * 2]
    if buf:
        out.append(buf)
    return out[:_MAX_CHUNKS]


def _words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r'[a-zа-яё0-9]{4,}', text.lower())}


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


async def _embed(texts: list[str]) -> list[list[float]] | None:
    from app.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled or not texts:
        return None
    try:
        return await llm.embed(texts)
    except Exception as exc:  # noqa: BLE001 — без эмбеддингов работает поиск по словам
        logger.warning('kb embed failed: %s', type(exc).__name__)
        return None


async def add_document(name: str, content: bytes, kind: str, author: str) -> dict[str, Any]:
    parsed = parse_reference(name, content)
    parts = chunks(parsed.text)
    vectors = await _embed(parts)
    with _lock:
        data = _load()
        doc_id = f'kb-{len(data["docs"]) + 1:03d}'
        while any(d['id'] == doc_id for d in data['docs']):
            doc_id = f'{doc_id}x'
        item = {
            'id': doc_id, 'name': name, 'kind': kind if kind in KINDS else 'other', 'author': author,
            'uploaded_at': now_iso(), 'chars': len(parsed.text), 'structure': parsed.structure[:60],
            'indexed': 'embeddings' if vectors else 'keywords',
            'chunks': [{'i': i, 'text': t, 'vec': vectors[i] if vectors else None} for i, t in enumerate(parts)],
        }
        data['docs'].append(item)
        _save(data)
    return public(item)


def public(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k != 'chunks'} | {'chunks': len(item.get('chunks', [])), 'kind_label': KINDS.get(item.get('kind', ''), '')}


def list_documents() -> list[dict[str, Any]]:
    return [public(d) for d in _load()['docs']]


def delete_document(doc_id: str) -> None:
    with _lock:
        data = _load()
        before = len(data['docs'])
        data['docs'] = [d for d in data['docs'] if d['id'] != doc_id]
        if len(data['docs']) == before:
            raise NotFound('Документ не найден')
        _save(data)


async def search(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Лучшие фрагменты по запросу: косинус эмбеддингов, иначе доля общих слов."""
    docs = _load()['docs']
    if not docs or not query.strip():
        return []
    qvec = None
    if any(c.get('vec') for d in docs for c in d['chunks']):
        got = await _embed([query[:2000]])
        qvec = got[0] if got else None
    qw = _words(query)
    scored = []
    for d in docs:
        for c in d['chunks']:
            if qvec and c.get('vec'):
                score = _cos(qvec, c['vec'])
            else:
                cw = _words(c['text'])
                score = len(qw & cw) / (len(qw) or 1)
            scored.append((score, d, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {'doc_id': d['id'], 'name': d['name'], 'kind': d['kind'], 'chunk': c['i'], 'score': round(s, 3), 'text': c['text'][:600]}
        for s, d, c in scored[:k]
        if s > 0.05
    ]


def templates() -> list[dict[str, Any]]:
    return [d for d in _load()['docs'] if d['kind'] == 'template']
