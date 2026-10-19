"""Хранение векторов базы знаний организации вне index.json (SPEC-KB-17)."""

import asyncio
import json
import os

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')


def test_vectors_in_npy_migration_search_and_reindex(tmp_path, monkeypatch) -> None:
    """SPEC-KB-17: векторы хранятся float32-матрицей на документ, старый index.json мигрирует, поиск идёт по косинусу, reindex догоняет документы без векторов."""
    from app.core.config import get_settings
    from app.kb import orgdocs

    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    get_settings.cache_clear()
    orgdocs._vec_cache.clear()
    kb = tmp_path / 'kb'
    kb.mkdir(parents=True)
    old = {'docs': [
        {'id': 'kb-001', 'name': 'a.txt', 'kind': 'regulation', 'indexed': 'embeddings',
         'chunks': [{'i': 0, 'text': 'про python', 'vec': [1.0, 0.0, 0.0]}, {'i': 1, 'text': 'про sql', 'vec': [0.0, 2.0, 0.0]}]},
        {'id': 'kb-002', 'name': 'b.txt', 'kind': 'other', 'indexed': 'keywords', 'chunks': [{'i': 0, 'text': 'про docker и сети', 'vec': None}]},
    ]}
    (kb / 'index.json').write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')

    async def fake_embed(texts):
        return [[0.0, 1.0, 0.0] if 'sql' in t else [0.0, 0.0, 1.0] for t in texts]

    monkeypatch.setattr(orgdocs, '_embed', fake_embed)
    hits = asyncio.run(orgdocs.search('sql запрос', k=3))
    data = json.loads((kb / 'index.json').read_text(encoding='utf-8'))
    assert not any('vec' in c for d in data['docs'] for c in d['chunks'])
    assert (kb / 'vectors' / 'kb-001.npy').exists() and not (kb / 'vectors' / 'kb-002.npy').exists()
    assert hits[0]['doc_id'] == 'kb-001' and hits[0]['chunk'] == 1 and hits[0]['score'] > 0.99
    r = asyncio.run(orgdocs.reindex())
    assert r == {'indexed': ['kb-002'], 'left': 0}
    hits = asyncio.run(orgdocs.search('docker', k=1))
    assert hits[0]['doc_id'] == 'kb-002'
    orgdocs.delete_document('kb-002')
    assert not (kb / 'vectors' / 'kb-002.npy').exists()
    get_settings.cache_clear()
