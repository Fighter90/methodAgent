"""Каркас по FR-05, FR-13, FR-14, FR-17, FR-22, FR-28: референс PDF, допущения, ТФ, часы тем, решения по пунктам, хронометраж."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import ProfStandard, TrudFunction, fit_plan  # noqa: E402

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')


@given(duration=st.integers(5, 400), mins=st.lists(st.integers(1, 120), min_size=1, max_size=10))
@settings(max_examples=200, deadline=None)
def test_fit_plan_sums_to_duration(duration: int, mins: list[int]) -> None:
    plan = [{'min': m, 'text': str(i)} for i, m in enumerate(mins)]
    out = fit_plan(plan, duration)
    assert sum(p['min'] for p in out) == duration
    assert [p['text'] for p in out] == [p['text'] for p in plan]


def test_match_tf_by_meaning() -> None:
    from app.skills.skeleton.run import match_tf

    ps = ProfStandard(code='06.001', title='Программист', order='', tf=[
        TrudFunction(code='A/01.3', title='Формализация и алгоритмизация поставленных задач'),
        TrudFunction(code='D/03.6', title='Проверка работоспособности и рефакторинг кода программного обеспечения'),
    ])
    assert match_tf('Проверяет работоспособность кода и выполняет рефакторинг', ps, 1) == ['D/03.6']
    assert match_tf('что угодно', ps, 2, proposed='A/01.3') == ['A/01.3']
    assert match_tf('что угодно', ps, 2, proposed='Z/99.9') == ['D/03.6']  # чужой код отклонён, порядок по номеру


def test_pdf_reference_hours_checked() -> None:
    fitz = pytest.importorskip('fitz')
    font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font.exists():
        pytest.skip('нет шрифта с кириллицей')
    from app.kb.files import parse_reference

    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname='dj', fontfile=str(font))
    rows = [['№', 'Наименование', 'Всего', 'ЛК', 'ПР', 'ЛБ', 'СРС'], ['1', 'Модуль', '10', '2', '4', '0', '4'],
            ['1.1', 'Тема', '6', '1', '2', '0', '3'], ['1.2', 'Тема 2', '4', '1', '2', '0', '1'], ['Итого', '', '10', '2', '4', '0', '6']]
    y = 50
    for r in rows:
        x = 40
        for c in r:
            page.draw_rect(fitz.Rect(x, y, x + 70, y + 20))
            page.insert_text((x + 3, y + 14), c, fontsize=9, fontname='dj')
            x += 70
        y += 20
    issues = parse_reference('ref.pdf', doc.tobytes()).hours_issues
    assert any('итоговая строка' in i and 'СРС 6' in i for i in issues)


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


def _skeleton(client, request: str = REQ) -> tuple[str, dict]:
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs', json={'request': request}, headers=h)
    assert r.status_code == 200, r.text
    pid = r.json()['program_id']
    doc = client.get(f'/api/v1/programs/{pid}', headers=h).json()
    if doc['status'] == 'questions':
        client.post(f'/api/v1/programs/{pid}/answers', json={'answers': {}}, headers=h)
    for _ in range(100):
        doc = client.get(f'/api/v1/programs/{pid}', headers=h).json()
        if doc['status'] == 'skeleton' and doc.get('report') and doc['modules']:
            break
        import time

        time.sleep(0.1)
    assert doc['status'] == 'skeleton', doc['status']
    return pid, doc


def test_topic_hours_manual_and_assumptions(client) -> None:
    h = _h(client, 'u-madina')
    pid, doc = _skeleton(client, 'Нужна программа «Основы Git» для разработчиков. Темы: ветки, слияние.')
    assert doc['report']['assumptions'], 'допущения агента видны в отчёте (FR-13)'
    assert all(a['note'] == 'принято агентом' for a in doc['report']['assumptions'])
    m = doc['modules'][0]
    t0, t1 = m['topics'][0], m['topics'][1]
    kind = max(('lk', 'pr', 'lb', 'srs'), key=lambda k: t1['hours'][k])
    new_v = t0['hours'][kind] + 1
    r = client.patch(f'/api/v1/programs/{pid}/skeleton', headers=h, json={'modules': [{'id': m['id'], 'topics': [
        {'id': t0['id'], 'hours': {kind: new_v}}, {'id': t1['id'], 'hours': {kind: t1['hours'][kind] - 1}}]}]})
    assert r.status_code == 200, r.text
    m2 = r.json()['program']['modules'][0]
    assert m2['topics'][0]['hours'][kind] == new_v
    assert m2['hours'][kind] == sum(t['hours'][kind] for t in m2['topics'])
    assert m2['hours']['total'] == m['hours']['total']
    # Следующая правка без часов тем не сбрасывает ручное распределение
    r = client.patch(f'/api/v1/programs/{pid}/skeleton', headers=h, json={'goal': 'Новая цель'})
    assert r.json()['program']['modules'][0]['topics'][0]['hours'][kind] == new_v


def test_decisions_per_node(client) -> None:
    from app.agent import workflow as wf
    from app.programs.schemas import ProgramDoc

    h = _h(client, 'u-madina')
    pid, doc = _skeleton(client)
    d = ProgramDoc.model_validate(client.get(f'/api/v1/programs/{pid}', headers=h).json())
    los = d.all_outcomes()[:2]
    los[0].text, los[1].text = 'Понимает основы pandas', 'Знаком с визуализацией'
    m = d.modules[0]
    m.topics[0].title, m.topics[1].title = 'Классы и объекты', 'Циклы и условия'
    d.report = wf.build_report(d, 'skeleton')
    v22 = [p for p in d.report.proposals if p['rule_id'] == 'V-22']
    v21 = [p for p in d.report.proposals if p['rule_id'] == 'V-21']
    assert len(v22) >= 2 and v21
    wf.decide(d, 'V-22', 'accept', 'u-madina', v22[0]['node'], v22[0]['proposal'])
    left = [p for p in d.report.proposals if p['rule_id'] == 'V-22' and not p['decided']]
    assert left, 'решение по одному РО не закрывает остальные (FR-22)'
    wf.decide(d, 'V-21', 'accept', 'u-madina', v21[0]['node'], v21[0]['proposal'])
    assert d.modules[0].topics[0].title == 'Циклы и условия'
    assert d.decisions[-1].node == v21[0]['node']


def test_calendar_kinds_and_lecture_plans(client) -> None:
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
    pid = r.json()['program_id']
    doc = client.get(f'/api/v1/programs/{pid}', headers=_h(client, 'u-madina')).json()
    weeks = doc['calendar']['schedule']
    assert sum(w['lk'] + w['pr'] + w['lb'] + w['srs'] + w['ia'] for w in weeks) == sum(w['hours'] for w in weeks) == doc['volume_h']
    for lec in doc['kit']['lectures']:
        assert sum(p['min'] for p in lec['plan']) == lec['duration_min'], lec['title']
