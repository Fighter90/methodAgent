"""Регрессии, найденные сквозным прогоном scripts/e2e_regression.py."""

from __future__ import annotations

import asyncio
import importlib
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

DISABLED = SimpleNamespace(enabled=False)

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str, role: str | None = None) -> dict[str, str]:
    body = {'user_id': user, 'password': 'demo'} | ({'role': role} if role else {})
    tok = client.post('/api/v1/auth/login', json=body).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture(scope='module')
def madina_program(client) -> str:
    """Программа, владелец которой — методист u-madina (адаптация методистом программы, собранной в режиме auto)."""
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=_h(client, 'u-api', 'methodist'))
    assert r.status_code == 200, r.text
    pid = r.json()['program_id']
    r = client.post(f'/api/v1/programs/{pid}/adapt', json={'volume_h': 36}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
    return r.json()['program_id']


def test_api_client_cannot_adapt_foreign_program(client, madina_program) -> None:
    """SPEC-FLOW-25: адаптация доступна API-клиенту только для своих программ — чужую он не копирует (403), свою адаптирует."""
    r = client.post(f'/api/v1/programs/{madina_program}/adapt', json={'volume_h': 36}, headers=_h(client, 'u-api'))
    assert r.status_code == 403, r.text
    assert r.json()['code'] == 'FORBIDDEN_ROLE'
    own = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=_h(client, 'u-api')).json()['program_id']
    r = client.post(f'/api/v1/programs/{own}/adapt', json={'volume_h': 36}, headers=_h(client, 'u-api'))
    assert r.status_code == 200, r.text


def test_unassigned_expert_cannot_read_sections_or_actualize(client, madina_program) -> None:
    """SPEC-AUTH-08: эксперт без назначенных модулей не читает программу ни карточкой, ни разделами, ни актуализацией (403)."""
    h = _h(client, 'u-timur')
    assert client.get(f'/api/v1/programs/{madina_program}', headers=h).status_code == 403
    assert client.get(f'/api/v1/programs/{madina_program}/sections', headers=h).status_code == 403
    assert client.get(f'/api/v1/programs/{madina_program}/actualize', headers=h).status_code == 403
    # методисту и руководителю разделы по-прежнему доступны
    assert client.get(f'/api/v1/programs/{madina_program}/sections', headers=_h(client, 'u-madina')).status_code == 200
    assert client.get(f'/api/v1/programs/{madina_program}/sections', headers=_h(client, 'u-ahmed')).status_code == 200


def test_intake_direction_from_kurs_po_phrase(monkeypatch) -> None:
    """SPEC-SKILLS-06: без модели направление берётся из оборота «курс по …», если нет названия и перечня тем (кейс 4)."""
    intake = importlib.import_module('app.skills.intake.run')
    monkeypatch.setattr(intake, 'get_llm', lambda: DISABLED)
    text = ('Сделайте курс по кибербезопасности для студентов колледжа, примерно на месяц, '
            'чтобы после него ребята могли пойти работать в эту сферу.')
    params, used = asyncio.run(intake.run(text))
    assert used is False
    assert params.direction == 'кибербезопасности'
    # название в кавычках и темы по-прежнему важнее оборота
    params, _ = asyncio.run(intake.run('Курс по Python на 36 часов. Темы: переменные, циклы и функции.'))
    assert params.direction == 'переменные'


def test_fallback_title_not_cut_mid_word(monkeypatch) -> None:
    """SPEC-SKILLS-13: каркас из библиотеки получает название направления, а не цель, обрезанную посреди слова с незакрытой «."""
    from app.programs.schemas import Params, ProgramType
    sk = importlib.import_module('app.skills.skeleton.run')
    monkeypatch.setattr(sk, 'get_llm', lambda: DISABLED)
    cyber = asyncio.run(sk.run(Params(volume_h=72, direction='кибербезопасности'), ProgramType.DPP_PK, None, []))
    assert cyber.source == 'cybersecurity' and cyber.title == 'Основы кибербезопасности'
    generic = asyncio.run(sk.run(Params(volume_h=36), ProgramType.DOOP, None, []))
    assert generic.title.count('«') == generic.title.count('»')
    assert not generic.title.endswith('направлен')
    assert sk._short_title('Сформировать практические навыки в области «Основы направления»') == 'Сформировать практические навыки в области'


def test_head_decisions_logged_in_words(client) -> None:
    """SPEC-API-12: решение руководителя попадает в журнал словами — и утверждение без комментария, и возврат."""
    hm, ht, hh = _h(client, 'u-madina'), _h(client, 'u-timur'), _h(client, 'u-ahmed')
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=hm)
    assert r.status_code == 200, r.text
    pid = r.json()['program_id']
    doc = client.get(f'/api/v1/programs/{pid}', headers=hm).json()
    for m in doc['modules']:
        assert client.put(f'/api/v1/programs/{pid}/modules/{m["id"]}/expert', json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    for task in client.get('/api/v1/reviews', headers=ht).json():
        if task['program_id'] != pid:
            continue
        mine = client.get(f'/api/v1/programs/{pid}', headers=ht).json()['kit']
        mid = task['module_id']
        items = [f'mp-{mid}'] * any(x['module_id'] == mid for x in mine['module_programs'])
        items += [x['id'] for k in ('lectures', 'questions', 'tasks') for x in mine[k] if x.get('module_id') == mid]
        for it in items:
            assert client.post(f'/api/v1/reviews/{task["rid"]}/decision', json={'decision': 'accept_item', 'node_id': it}, headers=ht).status_code == 200
        assert client.post(f'/api/v1/reviews/{task["rid"]}/decision', json={'decision': 'accept', 'score': 5}, headers=ht).status_code == 200
    assert client.post(f'/api/v1/programs/{pid}/submit', headers=hm).status_code == 200
    assert client.post(f'/api/v1/programs/{pid}/approval', json={'decision': 'return', 'comment': 'Уточните литературу'}, headers=hh).status_code == 200
    ev = client.get(f'/api/v1/programs/{pid}/events', headers=hh).json()
    assert ev[0]['action'] == 'returned' and ev[0]['text'] == 'Программа возвращена методисту: Уточните литературу'
    assert client.post(f'/api/v1/programs/{pid}/submit', headers=hm).status_code == 200
    assert client.post(f'/api/v1/programs/{pid}/approval', json={'decision': 'approve'}, headers=hh).status_code == 200
    ev = client.get(f'/api/v1/programs/{pid}/events', headers=hh).json()
    assert ev[0]['action'] == 'approved' and ev[0]['text'] == 'Программа утверждена руководителем'
