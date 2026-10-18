"""Нормативная база: выбор актов и ПС под открытые кейсы, выдержки актов в каркасе."""

import json

from app.kb import norms
from app.kb.registry import ROOT_DIR, norm_base_for, pick_ps, registry
from app.programs.schemas import ProgramType

CASES = {c['id']: c['request'] for c in json.loads((ROOT_DIR / 'testset' / 'cases.json').read_text(encoding='utf-8'))}


def ids(ptype: ProgramType, text: str) -> list[str]:
    return [s.id for s in norm_base_for(ptype, text)]


def test_repealed_acts_are_not_used():
    acts = {i['id'] for i in registry()['npa']}
    assert 'order-499' not in acts and 'order-816' not in acts
    assert all('утратил' not in str(i.get('status', '')).lower() for i in registry()['npa'])


def test_core_and_keyword_acts():
    dpp = ids(ProgramType.DPP_PK, CASES[3])
    assert dpp[:2] == ['law-273', 'order-266']
    assert 'decree-1678' not in dpp, 'очно-заочная форма сама по себе не означает ДОТ'
    assert 'law-152' in dpp, 'обезличенные данные — 152-ФЗ'
    ai = ids(ProgramType.DPP_PK, CASES[2])
    assert {'decree-1678', 'decree-490', 'letter-sk-702-08'} <= set(ai), 'ДОТ и ИИ в школе'
    assert 'decree-490' not in dpp
    doop = ids(ProgramType.DOOP, CASES[1])
    assert {'law-273', 'order-629', 'sanpin-sp-2-4-2-4283-26'} <= set(doop) and 'order-266' not in doop
    assert 'order-885-390' in ids(ProgramType.DPP_PK_INTERNSHIP, CASES[5])


def test_profstandards_for_cases():
    picked = {cid: pick_ps(CASES[cid]) for cid in (2, 3, 4, 5)}
    assert {cid: ps.code for cid, ps in picked.items()} == {2: '01.001', 3: '06.042', 4: '06.033', 5: '06.026'}
    assert all(0 < len(ps.tf) <= 12 for ps in picked.values())


def test_norm_digests_link_to_registry():
    acts = {i['id'] for i in registry()['npa']}
    docs = norms.norms()
    assert len(docs) >= 24
    assert all(d['npa_id'] in acts for d in docs if d['npa_id'])
    hits = norms.search('стажировка наставник практическая подготовка', 'dpp_pk_internship')
    assert hits and hits[0]['npa_id'] in ('order-885-390', 'order-266')
