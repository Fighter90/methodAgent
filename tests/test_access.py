"""Права и жизненный цикл по таблицам 19–21: 401 без токена, свои задания API-клиента, вычитка, откат, уведомления."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.kb.registry import registry

    registry.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture(scope='module')
def kit(client) -> str:
    """Комплект методиста (не автопрогон): владелец u-madina."""
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()['program_id']


def test_no_token_cannot_read_others(client, kit) -> None:
    """SPEC-AUTH-04, SPEC-EXPORT-10"""
    assert client.get(f'/api/v1/programs/{kit}').status_code == 401
    assert client.get(f'/api/v1/programs/{kit}/export/docx').status_code == 401
    assert all(p['id'] != kit for p in client.get('/api/v1/programs').json())


def test_auto_async_returns_202_and_job_result(client) -> None:
    """SPEC-API-06, SPEC-FLOW-02, SPEC-RULES-04"""
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ, 'wait': False})
    assert r.status_code == 202, r.text
    job = r.json()['job_id']
    for _ in range(200):
        info = client.get(f'/api/v1/jobs/{job}').json()
        if info['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert info['status'] == 'done', info
    assert info['result']['status'] in ('done', 'done_with_errors') and info['result']['report']['blocking_checks']


def test_expert_sees_only_own_modules_and_accepts_items(client, kit) -> None:
    """SPEC-API-12, SPEC-API-13, SPEC-API-14, SPEC-AUTH-08, SPEC-EXPORT-10, SPEC-FLOW-16, SPEC-FLOW-17, SPEC-FLOW-18"""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m1, m2 = doc['modules'][0]['id'], doc['modules'][1]['id']
    assert client.put(f'/api/v1/programs/{kit}/modules/{m1}/expert', json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    assert client.put(f'/api/v1/programs/{kit}/modules/{m2}/expert', json={'expert_id': 'u-olga'}, headers=hm).status_code == 200
    mine = client.get(f'/api/v1/programs/{kit}', headers=he).json()
    assert [m['id'] for m in mine['modules']] == [m1]
    assert {q['module_id'] for q in mine['kit']['questions']} == {m1}
    assert client.get(f'/api/v1/programs/{kit}/export/docx', headers=he).status_code == 403
    assert client.get(f'/api/v1/programs/{kit}/events', headers=he).status_code == 403
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    assert review['items_total'] > 1 and review['items_done'] == 0
    first = mine['kit']['questions'][0]['id']
    r = client.post(f'/api/v1/reviews/{review["rid"]}/decision', json={'decision': 'accept_item', 'node_id': first}, headers=he)
    assert r.status_code == 200, r.text
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    assert review['items_done'] == 1 and review['status'] == 'in_review'
    r = client.post(f'/api/v1/reviews/{review["rid"]}/comments', json={'text': 'Уточните формулировку'}, headers=he)
    assert r.status_code == 200
    notes = client.get('/api/v1/notifications', headers=hm).json()
    assert any('Уточните' in n['text'] for n in notes)
    assert client.post('/api/v1/notifications/read', json={}, headers=hm).json()['marked'] >= 1


def test_restore_does_not_bring_back_approval(client, kit) -> None:
    """SPEC-API-11, SPEC-API-12, SPEC-FLOW-22"""
    hm = _h(client, 'u-madina')
    from app.programs.schemas import Status

    vs = client.get(f'/api/v1/programs/{kit}/versions', headers=hm).json()
    r = client.post(f'/api/v1/programs/{kit}/versions/{vs[0]["version"]}/restore', headers=hm)
    assert r.status_code == 200
    assert r.json()['status'] not in (Status.APPROVED, Status.ON_APPROVAL)
    ev = client.get(f'/api/v1/programs/{kit}/events', headers=hm).json()
    assert ev[0]['action'] == 'restore' and ev[0]['before'] and ev[0]['version'] > 1


def test_json_export_follows_schema_48(client, kit) -> None:
    """SPEC-EXPORT-04"""
    import json

    hm = _h(client, 'u-madina')
    data = json.loads(client.get(f'/api/v1/programs/{kit}/export/json', headers=hm).content)
    prog = data['program']
    assert {'id', 'type', 'volume_h', 'competencies', 'modules', 'questions', 'tasks', 'lectures', 'final_assessment'} <= set(prog)
    assert 'usage' not in prog and 'params' not in prog
    assert prog['competencies'][0]['indicators'][0]['outcomes']
    assert {'total', 'lk', 'pr', 'lb', 'srs'} == set(prog['modules'][0]['hours'])


def test_edit_hours_keeps_module_total_and_text_edit_finds_target(client, kit) -> None:
    """SPEC-AUTH-09, SPEC-FLOW-13, SPEC-FLOW-14"""
    hm = _h(client, 'u-madina')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m = doc['modules'][0]
    t = m['topics'][0]
    want = {'srs': t['hours']['srs'] + 1}
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want, 'dry_run': True}, headers=hm)
    assert r.status_code == 200 and 'Тема' in r.json()['preview']['after']
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want}, headers=hm)
    if r.status_code == 409:
        assert r.json()['code'] in ('HOURS_MISMATCH', 'EDIT_REJECTED')
    else:
        after = r.json()['program']['modules'][0]
        assert after['hours']['total'] == m['hours']['total']
        assert sum(x['hours']['total'] for x in after['topics']) == m['hours']['total']
    word = t['title'].split()[0]
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': '', 'instruction': f'{word}: добавить пример', 'dry_run': True}, headers=hm)
    assert r.status_code == 200 and r.json()['target']
    he = _h(client, 'u-timur')
    assert client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want}, headers=he).status_code == 403


def test_module_accept_requires_all_items(client, kit) -> None:
    """SPEC-API-02, SPEC-API-13, SPEC-FLOW-17"""
    he = _h(client, 'u-timur')
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json())
    r = client.post(f'/api/v1/reviews/{review["rid"]}/decision', json={'decision': 'accept'}, headers=he)
    assert r.status_code == 409 and r.json()['code'] == 'ITEMS_NOT_CHECKED'


def test_admin_profile_registry_and_expert_suggestions(client, kit) -> None:
    """SPEC-FLOW-29, SPEC-KB-14, SPEC-KB-15, SPEC-SKILLS-09"""
    ha, hm = _h(client, 'u-admin'), _h(client, 'u-madina')
    assert client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 36}}, headers=hm).status_code == 403
    r = client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 36, 'form': 'очная'}}, headers=ha)
    assert r.status_code == 200 and r.json()['defaults']['volume_h'] == 36
    from app.skills.clarify.run import default_for

    assert default_for('volume_h') == 36
    assert client.put('/api/v1/org/profile', json={'bogus': 1}, headers=ha).status_code == 400
    items = client.get('/api/v1/org/registry?kind=tools', headers=ha).json()
    assert items
    ps = client.get('/api/v1/org/registry?kind=ps', headers=ha).json()
    r = client.put('/api/v1/org/registry', json={'kind': 'ps', 'items': ps}, headers=ha)
    assert r.status_code == 200 and r.json()['items'] == len(ps)
    assert all(x.get('checked_at') for x in client.get('/api/v1/org/registry?kind=ps', headers=ha).json())
    sug = client.get(f'/api/v1/programs/{kit}/experts', headers=hm).json()
    assert sug['experts'] and len(sug['suggestions']) == len(client.get(f'/api/v1/programs/{kit}', headers=hm).json()['modules'])
    client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 72, 'form': 'очно-заочная'}}, headers=ha)


def test_head_sees_quality_and_owners(client, kit) -> None:
    """SPEC-FLOW-20, SPEC-FLOW-21"""
    hh = _h(client, 'u-ahmed')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hh).json()
    q = doc['quality']
    assert {'human_edit_share', 'accepted_without_edits', 'expert_score', 'code_ok_share', 'work_days', 'generation_rub'} <= set(q)
    assert all(o['owner'] for o in doc['readiness']['open'])
    assert any('эксперт' in o['owner'] for o in doc['readiness']['open'])


def test_unassigned_expert_cannot_accept_and_api_404(client, kit) -> None:
    """SPEC-API-01, SPEC-API-05, SPEC-AUTH-09, SPEC-FLOW-17"""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    free = next((m for m in doc['modules'] if not m['expert_id']), None)
    if free:
        r = client.post(f'/api/v1/programs/{kit}/reviews/decision', json={'module_id': free['id'], 'decision': 'accept'}, headers=he)
        assert r.status_code == 403
    mine = next(m for m in doc['modules'] if m['expert_id'] == 'u-timur')
    r = client.post(f'/api/v1/programs/{kit}/reviews/decision', json={'module_id': mine['id'], 'decision': 'accept'}, headers=he)
    if r.status_code == 409:
        assert r.json()['details']['missing']
    r = client.get('/api/v1/no-such-method')
    assert r.status_code == 404 and r.headers['content-type'].startswith('application/json')
    assert client.get('/api/v1/health').json()['status'] == 'ok'
