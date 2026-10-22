"""Архив программ методиста (specs/programs-service.md, SPEC-SVC-18…21)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

REQ = ('Нужна программа повышения квалификации на 36 часов «Excel и Power BI для экономистов», '
       'очно-заочно, 2 недели. Итоговая аттестация — защита проекта.')


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
def prog(client) -> tuple[str, str]:
    hm = _h(client, 'u-madina')
    j = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=hm).json()
    m1 = j['kit']['program']['modules'][0]['id']
    assert client.put(f"/api/v1/programs/{j['program_id']}/modules/{m1}/expert", json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    return j['program_id'], m1


def _ids(client, h, query: str = '') -> list[str]:
    return [x['id'] for x in client.get(f'/api/v1/programs{query}', headers=h).json()]


def test_archive_only_methodist(client, prog) -> None:
    """SPEC-SVC-18: убирать в архив и возвращать может только методист; руководитель, эксперт и администратор получают 403."""
    pid, _ = prog
    for user in ('u-ahmed', 'u-timur', 'u-admin'):
        assert client.post(f'/api/v1/programs/{pid}/archive', headers=_h(client, user)).status_code == 403
        assert client.post(f'/api/v1/programs/{pid}/unarchive', headers=_h(client, user)).status_code == 403


def test_archive_hides_from_methodist_list_and_reviews(client, prog) -> None:
    """SPEC-SVC-19: архивная программа скрыта из списка методиста по умолчанию и из «Вычитки модулей» эксперта,
    видна в фильтре archived=true; у руководителя видна как раньше с признаком архива; версия не меняется, событие в журнале."""
    pid, _ = prog
    hm, hh, he = _h(client, 'u-madina'), _h(client, 'u-ahmed'), _h(client, 'u-timur')
    version = client.get(f'/api/v1/programs/{pid}', headers=hm).json()['version']
    assert pid in _ids(client, hm) and any(r['program_id'] == pid for r in client.get('/api/v1/reviews', headers=he).json())
    r = client.post(f'/api/v1/programs/{pid}/archive', headers=hm)
    assert r.status_code == 200, r.text
    assert r.json()['archived_at'] and r.json()['archived_by'] == 'u-madina'
    assert pid not in _ids(client, hm)
    assert _ids(client, hm, '?archived=true') == [pid]
    assert pid in _ids(client, hm, '?archived=all')
    head = next(x for x in client.get('/api/v1/programs', headers=hh).json() if x['id'] == pid)
    assert head['archived_at']
    assert not any(r['program_id'] == pid for r in client.get('/api/v1/reviews', headers=he).json())
    doc = client.get(f'/api/v1/programs/{pid}', headers=hm).json()
    assert doc['version'] == version and doc['archived_at']
    assert any(e['action'] == 'archive' for e in client.get(f'/api/v1/programs/{pid}/events', headers=hm).json())


def test_archived_is_read_only_until_returned(client, prog) -> None:
    """SPEC-SVC-20: архивная программа открывается и выгружается, а изменяющие действия отклоняются 409 ARCHIVED до возврата;
    возврат восстанавливает программу в списке с прежним статусом."""
    pid, m1 = prog
    hm = _h(client, 'u-madina')
    status = client.get(f'/api/v1/programs/{pid}', headers=hm).json()['status']
    assert client.get(f'/api/v1/programs/{pid}/export/docx', headers=hm).status_code == 200
    r = client.post(f'/api/v1/programs/{pid}/submit', headers=hm)
    assert r.status_code == 409 and r.json()['code'] == 'ARCHIVED'
    r = client.put(f'/api/v1/programs/{pid}/modules/{m1}/expert', json={'expert_id': 'u-olga'}, headers=hm)
    assert r.status_code == 409
    r = client.post(f'/api/v1/programs/{pid}/unarchive', headers=hm)
    assert r.status_code == 200 and not r.json()['archived_at']
    assert pid in _ids(client, hm) and pid not in _ids(client, hm, '?archived=true')
    assert client.get(f'/api/v1/programs/{pid}', headers=hm).json()['status'] == status


def test_archive_conflicts(client, prog) -> None:
    """SPEC-SVC-21: программу на утверждении или со сборкой в процессе нельзя убрать в архив (409); повторный архив — 409."""
    from app.programs import service as svc
    from app.programs.schemas import Status

    pid, _ = prog
    hm = _h(client, 'u-madina')
    for st in (Status.ON_APPROVAL, Status.GENERATING):
        doc = client.portal.call(svc.load, pid)
        doc.status = st
        client.portal.call(svc.save, doc)
        r = client.post(f'/api/v1/programs/{pid}/archive', headers=hm)
        assert r.status_code == 409, r.text
    doc = client.portal.call(svc.load, pid)
    doc.status = Status.KIT_READY
    client.portal.call(svc.save, doc)
    assert client.post(f'/api/v1/programs/{pid}/archive', headers=hm).status_code == 200
    assert client.post(f'/api/v1/programs/{pid}/archive', headers=hm).status_code == 409
    assert client.post(f'/api/v1/programs/{pid}/unarchive', headers=hm).status_code == 200
