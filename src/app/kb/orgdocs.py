"""База знаний организации (FR-09): шаблоны, положения и иные документы АЦР.

Администратор загружает документ — текст режется на фрагменты и индексируется
эмбеддингами шлюза (Giga-Embeddings). Без модели поиск идёт по пересечению слов.
Найденные фрагменты попадают в программу со ссылкой на документ-источник.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import NotFound
from app.kb.files import parse_reference

logger = logging.getLogger(__name__)

KINDS = {'template': 'Шаблон программы', 'regulation': 'Положение', 'other': 'Иной документ'}
_CHUNK = 900
_MAX_CHUNKS = 200
_lock = threading.RLock()


def _dir():
    d = get_settings().data_dir / 'kb'
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path():
    return _dir() / 'index.json'


def _vec_path(doc_id: str):
    d = _dir() / 'vectors'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{doc_id}.npy'


# Векторы хранятся отдельно от текстов: float32-матрица на документ (data/kb/vectors/<id>.npy),
# строки нормированы. В памяти держится кэш матриц; index.json — только тексты и метаданные.
_vec_cache: dict[str, np.ndarray] = {}


def _write_vectors(doc_id: str, vectors: list[list[float]]) -> None:
    m = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    m = m / norms
    p = _vec_path(doc_id)
    tmp = p.with_name(p.stem + '.tmp.npy')
    np.save(tmp, m)
    tmp.replace(p)
    _vec_cache[doc_id] = m


def _vectors(doc_id: str) -> np.ndarray | None:
    m = _vec_cache.get(doc_id)
    if m is None:
        p = _vec_path(doc_id)
        if not p.exists():
            return None
        m = np.load(p, mmap_mode='r')
        _vec_cache[doc_id] = m
    return m


def _migrate(data: dict[str, Any]) -> bool:
    """Старый формат: векторы внутри index.json. Переносит их в .npy и убирает из JSON."""
    moved = False
    for d in data['docs']:
        vecs = [c.get('vec') for c in d.get('chunks', [])]
        if any(v is not None for v in vecs):
            if all(v is not None for v in vecs):
                _write_vectors(d['id'], vecs)
                d['indexed'] = 'embeddings'
            else:
                d['indexed'] = 'keywords'
            moved = True
        for c in d.get('chunks', []):
            c.pop('vec', None)
    return moved


def _load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {'docs': []}
    data = json.loads(p.read_text(encoding='utf-8'))
    if any('vec' in c for d in data['docs'] for c in d.get('chunks', [])):
        with _lock:
            if _migrate(data):
                logger.info('kb: векторы перенесены из index.json в data/kb/vectors')
            _save(data)
    return data


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


async def _embed(texts: list[str]) -> list[list[float]] | None:
    from app.llm.client import LLMUnavailable, get_llm

    llm = get_llm()
    if not llm.enabled or not texts:
        return None
    try:
        return await llm.embed(texts)
    except LLMUnavailable as exc:  # без эмбеддингов работает поиск по словам
        logger.warning('kb embed failed, поиск по словам: %s', str(exc)[:200])
        return None


async def add_document(name: str, content: bytes, kind: str, author: str) -> dict[str, Any]:
    parsed = await asyncio.to_thread(parse_reference, name, content)
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
            'chunks': [{'i': i, 'text': t} for i, t in enumerate(parts)],
        }
        if vectors:
            _write_vectors(doc_id, vectors)
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
        _vec_cache.pop(doc_id, None)
        _vec_path(doc_id).unlink(missing_ok=True)


async def search(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Лучшие фрагменты по запросу: косинус эмбеддингов (матрица float32), иначе доля общих слов."""
    from app.kb.abbr import expand

    docs = _load()['docs']
    if not docs or not query.strip():
        return []
    query = expand(query)  # сокращения расшифровываются и для эмбеддинга, и для поиска по словам
    mats = {d['id']: _vectors(d['id']) for d in docs if d.get('indexed') == 'embeddings'}
    qvec = None
    if any(m is not None for m in mats.values()):
        got = await _embed([query[:2000]])
        if got:
            q = np.asarray(got[0], dtype=np.float32)
            qvec = q / (np.linalg.norm(q) or 1.0)
    qw = _words(query)
    sims_by_doc = {}
    for d in docs:
        m = mats.get(d['id'])
        if qvec is not None and m is not None and m.shape[1] == qvec.shape[0]:
            sims_by_doc[d['id']] = np.asarray(m) @ qvec
    # Одна шкала, пока часть документов без векторов: доля общих слов (до 1,0) не должна обгонять
    # косинус (обычно 0,3–0,6), поэтому фрагмент только по словам получает не больше половины лучшего косинуса
    best_cos = max((float(v.max()) for v in sims_by_doc.values() if len(v)), default=0.0)
    lex_scale = 0.5 * best_cos if best_cos > 0 else 1.0
    scored = []
    for d in docs:
        sims = sims_by_doc.get(d['id'])
        for c in d['chunks']:
            if sims is not None and c['i'] < len(sims):
                score = float(sims[c['i']])
            else:
                cw = _words(c['text'])
                score = lex_scale * len(qw & cw) / (len(qw) or 1)
            scored.append((score, d, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {'doc_id': d['id'], 'name': d['name'], 'kind': d['kind'], 'chunk': c['i'], 'score': round(s, 3), 'text': c['text'][:600]}
        for s, d, c in scored[:k]
        if s > 0.05
    ]


async def reindex(limit_docs: int = 10) -> dict[str, Any]:
    """Догоняет эмбеддингами документы, проиндексированные только по словам (по limit_docs за вызов)."""
    data = _load()
    todo = [d for d in data['docs'] if d.get('indexed') != 'embeddings' or _vectors(d['id']) is None][:limit_docs]
    done = []
    for d in todo:
        vectors = await _embed([c['text'] for c in d['chunks']])
        if not vectors:
            break
        with _lock:
            _write_vectors(d['id'], vectors)
            fresh = _load()
            for x in fresh['docs']:
                if x['id'] == d['id']:
                    x['indexed'] = 'embeddings'
            _save(fresh)
        done.append(d['id'])
    left = sum(1 for d in _load()['docs'] if d.get('indexed') != 'embeddings')
    return {'indexed': done, 'left': left}


def templates() -> list[dict[str, Any]]:
    return [d for d in _load()['docs'] if d['kind'] == 'template']
