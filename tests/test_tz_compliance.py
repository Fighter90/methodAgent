"""Исправления по сверке с ТЗ (docs/tz-compliance.md): автопрогон стажировки, шапки таблиц АЦР, лимит входа."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _auto(client, case_id: int) -> dict:
    case = next(c for c in json.loads((ROOT / 'testset' / 'cases.json').read_text()) if c['id'] == case_id)
    atts = [{'name': Path(a).name, 'content_base64': base64.b64encode((ROOT / a).read_bytes()).decode()} for a in case['attachments']]
    r = client.post('/api/v1/programs?mode=auto', json={'request': case['request'], 'attachments': atts, 'answers': case['answers']})
    assert r.status_code == 200
    return r.json()


def _tables(client, program_id: str) -> list[list[list[str]]]:
    from docx import Document

    d = client.get(f'/api/v1/programs/{program_id}/export/docx')
    assert d.status_code == 200
    doc = Document(io.BytesIO(d.content))
    return [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables]


def test_auto_calendar_choice_refreshes_skeleton_report(client) -> None:
    """SPEC-FLOW-35: после выбора варианта графика в auto каркас утверждается правилом auto-approve без ложной пометки об ошибках ✕."""
    j = _auto(client, 5)
    assert j['status'] == 'done'
    assert j['skeleton']['calendar']['chosen_option'] == 'six_days'
    assert not any('Каркас содержит ошибки' in n for n in j['agent_notes'])
    approvals = j['kit']['program']['approvals']
    assert any(a['stage'] == 'skeleton' and a['actor'] == 'auto-approve' and a['decision'] == 'approve' for a in approvals)


def test_dpp_curriculum_and_utp_headers_follow_template(client) -> None:
    """SPEC-EXPORT-12: шапки УП и УТП ДПП ПК совпадают с образцом АЦР (в УТП — «разделов, тем» и «Форма контроля»)."""
    j = _auto(client, 3)
    heads = [t[0] for t in _tables(client, j['program_id']) if t and t[0][:1] == ['№ п/п']]
    assert heads[0][1] == 'Наименование разделов программы' and heads[0][-1] == 'Форма аттестации'
    assert heads[1][1] == 'Наименование разделов, тем программы' and heads[1][-1] == 'Форма контроля'


def test_doop_staff_table_with_blank_names(client) -> None:
    """SPEC-EXPORT-13: в ДООП раздел 3.4 содержит таблицу образца по модулям УП с пустыми ФИО, степенью и должностью."""
    j = _auto(client, 1)
    staff = next(t for t in _tables(client, j['program_id']) if t[0][:3] == ['№', 'Модуль/Дисциплина в соответствии с УП', 'ФИО преподавателя'])
    modules = j['skeleton']['modules']
    assert len(staff) == 1 + len(modules) + 1  # шапка, модули, итоговая аттестация
    assert all(row[2] == row[3] == row[4] == '' for row in staff[1:])
    assert staff[1][1].endswith(modules[0]['title'])


def test_login_failures_rate_limited(client) -> None:
    """SPEC-AUTH-24: после 5 неудачных попыток входа в минуту с одного адреса вход отвечает 429 RATE_LIMIT."""
    from app.auth import router as auth_router

    ip = {'x-forwarded-for': '10.250.0.7'}
    try:
        for _ in range(5):
            assert client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'nope'}, headers=ip).status_code == 401
        r = client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'demo'}, headers=ip)
        assert r.status_code == 429 and r.json()['code'] == 'RATE_LIMIT'
        # другой адрес не затронут
        assert client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'demo'}, headers={'x-forwarded-for': '10.250.0.8'}).status_code == 200
    finally:
        auth_router._login_failures.clear()


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


def test_expert_comment_proposal_needs_expert_confirmation(client) -> None:
    """SPEC-FLOW-36: правка агента по замечанию эксперта ограничена его модулем, не меняет часы и РО и применяется только после подтверждения экспертом."""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    req = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
           'очно-заочно, 4 недели. Итоговая аттестация — защита проекта.')
    j = client.post('/api/v1/programs?mode=auto', json={'request': req}, headers=hm).json()
    pid, mods = j['program_id'], j['kit']['program']['modules']
    m1, m2 = mods[0]['id'], mods[1]['id']
    assert client.put(f'/api/v1/programs/{pid}/modules/{m1}/expert', json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    task = next(t for t in j['kit']['program']['tasks'] if t['module_id'] == m1)
    before = client.get(f'/api/v1/programs/{pid}', headers=hm).json()
    # чужой модуль эксперту недоступен
    assert client.post(f'/api/v1/programs/{pid}/comments', json={'module_id': m2, 'text': 'x', 'ask_agent': True}, headers=he).status_code == 403
    r = client.post(f'/api/v1/programs/{pid}/comments', json={'module_id': m1, 'node_id': task['id'], 'text': 'Добавьте банковский пример', 'ask_agent': True}, headers=he)
    assert r.status_code == 200
    c = r.json()['comment']
    assert c['status'] == 'proposed' and c['agent_proposal']
    # методист не применяет правку за эксперта: она остаётся на подтверждении
    r = client.post(f'/api/v1/programs/{pid}/comments/answer', json={'comment_id': c['id'], 'apply_proposal': True}, headers=hm)
    assert r.json()['comment']['status'] == 'proposed'
    r = client.post(f'/api/v1/programs/{pid}/comments/answer', json={'comment_id': c['id'], 'apply_proposal': True}, headers=he)
    assert r.status_code == 200 and r.json()['comment']['status'] == 'applied'
    after = r.json()['program']
    assert [m['hours'] for m in after['modules']] == [m['hours'] for m in before['modules']]
    assert [c2['indicators'] for c2 in after['competencies']] == [c2['indicators'] for c2 in before['competencies']]


_module = st.tuples(st.floats(0.1, 5), st.floats(0, 0.5), st.floats(0, 0.5), st.integers(0, 2), st.integers(1, 5))


@given(volume=st.integers(16, 500), final=st.integers(0, 8), mods=st.lists(_module, min_size=1, max_size=8), internship=st.booleans())
@settings(max_examples=150, deadline=None)
def test_solver_property_all_levels(volume: int, final: int, mods: list, internship: bool) -> None:
    """SPEC-SOLVER-04, SPEC-SOLVER-05, SPEC-SOLVER-06, SPEC-SOLVER-07: для любого объёма 16–500 ч суммы сходятся на всех уровнях, вход детерминирован, в стажировке ЛК = ПР = ЛБ = 0 (ТЗ, 4.11)."""
    from app.solver.hours import ModuleIn, TopicIn, solve

    modules = [ModuleIn(title=f'М{i}', weight=w, lk_share=lk, srs_share=srs, lb_hours=lb, topics=[TopicIn(f'Т{i}.{k}') for k in range(nt)])
               for i, (w, lk, srs, lb, nt) in enumerate(mods)]
    res = solve(volume=volume, final_hours=final, modules=modules, internship=internship)
    assert res.totals.total + res.final_hours == volume
    for kind in ('total', 'lk', 'pr', 'lb', 'srs'):
        assert sum(getattr(m.hours, kind) for m in res.modules) == getattr(res.totals, kind)
    for m in res.modules:
        h = m.hours
        assert min(h.lk, h.pr, h.lb, h.srs) >= 0 and h.lk + h.pr + h.lb + h.srs == h.total
        for kind in ('total', 'lk', 'pr', 'lb', 'srs'):
            assert sum(getattr(r, kind) for _, r in m.topics) == getattr(h, kind)
        if internship:
            assert h.lk == h.pr == h.lb == 0 and all(r.lk == r.pr == r.lb == 0 for _, r in m.topics)
    again = solve(volume=volume, final_hours=final, modules=modules, internship=internship)
    assert [(m.hours, m.topics) for m in again.modules] == [(m.hours, m.topics) for m in res.modules]


def test_changed_accepted_module_returns_to_review_and_notifies_expert(client) -> None:
    """SPEC-FLOW-37: правка принятого модуля возвращает его на вычитку и уведомляет назначенного эксперта."""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-olga')
    req = ('Нужна программа повышения квалификации на 36 часов «SQL для аналитиков» для сотрудников банков, '
           'очно, итоговая аттестация — зачёт.')
    j = client.post('/api/v1/programs?mode=auto', json={'request': req}, headers=hm).json()
    pid, m1 = j['program_id'], j['kit']['program']['modules'][0]
    assert client.put(f'/api/v1/programs/{pid}/modules/{m1["id"]}/expert', json={'expert_id': 'u-olga'}, headers=hm).status_code == 200
    rid = f'{pid}__{m1["id"]}'
    r = client.post(f'/api/v1/reviews/{rid}/decision', json={'decision': 'accept'}, headers=he)
    assert r.status_code == 409
    for node in r.json()['details']['missing']:
        assert client.post(f'/api/v1/reviews/{rid}/decision', json={'decision': 'accept_item', 'node_id': node}, headers=he).status_code == 200
    assert client.post(f'/api/v1/reviews/{rid}/decision', json={'decision': 'accept', 'score': 5}, headers=he).status_code == 200
    client.post('/api/v1/notifications/read', json={}, headers=he)
    topic = m1['topics'][0]
    r = client.post(f'/api/v1/programs/{pid}/edits', json={'target': topic['id'], 'new_title': topic['title'] + ' на практике'}, headers=hm)
    assert r.status_code == 200, r.text
    assert next(m for m in r.json()['program']['modules'] if m['id'] == m1['id'])['review_status'] == 'in_review'
    notes = client.get('/api/v1/notifications', headers=he).json()
    assert any('вернулся на вычитку' in n['text'] and not n.get('read') for n in notes)
