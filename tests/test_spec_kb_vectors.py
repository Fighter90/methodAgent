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


def test_mixed_index_keeps_semantic_hits_on_top(tmp_path, monkeypatch) -> None:
    """SPEC-KB-18: пока часть документов без векторов, фрагмент, найденный только по словам, не обгоняет лучший косинус: его оценка не больше половины лучшего косинуса."""
    from app.core.config import get_settings
    from app.kb import orgdocs

    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    get_settings.cache_clear()
    orgdocs._vec_cache.clear()
    kb = tmp_path / 'kb'
    kb.mkdir(parents=True)
    old = {'docs': [
        {'id': 'kb-001', 'name': 'sem.txt', 'kind': 'regulation', 'indexed': 'embeddings',
         'chunks': [{'i': 0, 'text': 'организация практики обучающихся', 'vec': [0.4, 0.9165, 0.0]}]},
        {'id': 'kb-002', 'name': 'lex.txt', 'kind': 'other', 'indexed': 'keywords',
         'chunks': [{'i': 0, 'text': 'практическая подготовка', 'vec': None}]},
    ]}
    (kb / 'index.json').write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')

    async def fake_embed(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(orgdocs, '_embed', fake_embed)
    hits = asyncio.run(orgdocs.search('практическая подготовка', k=2))
    assert [h['doc_id'] for h in hits] == ['kb-001', 'kb-002']
    assert hits[1]['score'] <= hits[0]['score'] / 2 + 1e-6


def test_kb_search_fuses_org_and_norms_by_rank() -> None:
    """SPEC-KB-19: выдача /kb/search сливает документы организации и выжимки норм по местам в своих выдачах, а не по сырым оценкам разных шкал; при равном месте документ организации идёт первым."""
    from app.programs.extra_router import fuse

    org = [{'doc_id': 'kb-1', 'kind': 'regulation', 'score': 0.38}, {'doc_id': 'kb-2', 'kind': 'regulation', 'score': 0.31}]
    law = [{'doc_id': 'n-1', 'kind': 'norm', 'score': 1.15}, {'doc_id': 'n-2', 'kind': 'norm', 'score': 0.9}]
    assert [h['doc_id'] for h in fuse(org, law, 3)] == ['kb-1', 'n-1', 'kb-2']
    assert [h['doc_id'] for h in fuse([], law, 5)] == ['n-1', 'n-2']


def test_abbreviations_expanded_in_search() -> None:
    """SPEC-KB-20: сокращения образования в запросе (ДО, ДПО, СПО, ПС, ОВЗ…) расшифровываются для поиска, только целым словом в верхнем регистре; «педагог ДО» находит профстандарт 01.003."""
    from app.kb import norms
    from app.kb.abbr import expand

    assert 'дополнительное образование' in expand('квалификация педагога ДО')
    assert expand('работа до вечера') == 'работа до вечера'
    assert expand('ДОТ и ЭО') == 'ДОТ и ЭО (дистанционные образовательные технологии; электронное обучение)'
    top = norms.search('квалификация педагога ДО', k=3)
    assert any('01.003' in h['name'] for h in top)


def test_recognition_normalizes_writing() -> None:
    """SPEC-KB-21: распознавание инструментов живёт в переиспользуемом слое kb/recognition и переживает кривое написание.

    «PоstgreS 12» — намешаны латиница и кириллица, «питоон 3.7» — сдвоенная буква,
    «k8s 1.25» — обычное написание не сломано; находки сливаются без дубликатов.
    """
    from app.agent import extras
    from app.kb.recognition import scan_tools

    found = scan_tools('PоstgreS 12, питоон 3.7 и k8s 1.25')
    got = {(f['kind'], f['found'].lower()) for f in found}
    assert any(k == 'version' and 'postgres' in x for k, x in got), found
    assert any(k == 'version' and 'питон' in x for k, x in got), found
    assert any(k == 'version' and 'k8s' in x for k, x in got), found
    assert len(got) == len(found), found  # дубликатов между вариантами нормализации нет
    assert any('постгрес' in f['found'] for f in scan_tools('постгрес 13'))  # каноничное написание не потерялось
    assert extras.scan_text('k8s 1.25') == scan_tools('k8s 1.25')  # обёртка extras — тот же сканер
