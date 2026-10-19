"""Базовые проверки: солвер часов (таблица 16 ТЗ) и автопрогон пяти открытых запросов."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.solver.hours import largest_remainder  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@given(total=st.integers(1, 500), weights=st.lists(st.floats(0.1, 10), min_size=1, max_size=12))
@settings(max_examples=200, deadline=None)
def test_largest_remainder_sums(total: int, weights: list[float]) -> None:
    """SPEC-SOLVER-01"""
    parts = largest_remainder(total, weights)
    assert sum(parts) == total
    assert all(p >= 0 for p in parts)


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.mark.parametrize('case_id', [1, 2, 3, 4, 5])
def test_open_cases_auto(client, case_id: int) -> None:
    """SPEC-API-07, SPEC-EXPORT-02, SPEC-FLOW-02, SPEC-FLOW-03, SPEC-RULES-04, SPEC-RULES-05, SPEC-RULES-20, SPEC-SKILLS-05, SPEC-SOLVER-04, SPEC-SOLVER-05, SPEC-SOLVER-06"""
    import base64

    case = next(c for c in json.loads((ROOT / 'testset' / 'cases.json').read_text()) if c['id'] == case_id)
    atts = [{'name': Path(a).name, 'content_base64': base64.b64encode((ROOT / a).read_bytes()).decode()} for a in case['attachments']]
    r = client.post('/api/v1/programs?mode=auto', json={'request': case['request'], 'attachments': atts, 'answers': case['answers']})
    assert r.status_code == 200
    j = r.json()
    assert j['skeleton']['totals']['all'] == {1: 16, 2: 36, 3: 72, 4: 72, 5: 256}[case_id]
    assert j['report']['blocking_checks'] == '10/10'
    for m in j['skeleton']['modules']:
        assert m['lk'] + m['pr'] + m['lb'] + m['srs'] == m['total']
        assert sum(t['total'] for t in m['topics']) == m['total']
    d = client.get(f'/api/v1/programs/{j["program_id"]}/export/docx')
    assert d.status_code == 200 and d.content[:2] == b'PK'


def test_roles(client) -> None:
    """SPEC-AUTH-06, SPEC-AUTH-07"""
    tok = client.post('/api/v1/auth/login', json={'user_id': 'u-timur', 'password': 'demo'}).json()['access_token']
    r = client.post('/api/v1/programs', json={'request': 'Курс Python 16 часов для школьников'}, headers={'Authorization': f'Bearer {tok}'})
    assert r.status_code == 403
