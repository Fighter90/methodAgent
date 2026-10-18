"""Вход по логину, регистрация с минимальными правами, личный кабинет и администрирование: пользователи, ключи, навыки."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _login(client, login: str, password: str = 'demo') -> dict:
    r = client.post('/api/v1/auth/login', json={'login': login, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f'Bearer {r.json()["access_token"]}'}


def test_login_by_login_id_and_all_demo_users(client) -> None:
    cfg = client.get('/api/v1/auth/config').json()
    assert {u['login'] for u in cfg['demo_accounts']} == {'madina', 'timur', 'olga', 'ahmed', 'admin', 'api'}
    assert cfg['sso']['available'] is False
    for u in cfg['demo_accounts']:
        r = client.post('/api/v1/auth/login', json={'login': u['login'], 'password': cfg['demo_password']})
        assert r.status_code == 200 and r.json()['user']['role'] == u['role']
    assert client.post('/api/v1/auth/login', json={'user_id': 'u-api', 'password': 'demo'}).status_code == 200
    assert client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'nope'}).status_code == 401
    # токен в X-MA-Token (так шлёт интерфейс: хаб перехватывает Authorization)
    tok = client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'demo'}).json()['access_token']
    assert client.get('/api/v1/auth/me', headers={'X-MA-Token': tok}).json()['login'] == 'madina'
    assert client.get('/api/v1/auth/me', headers={'X-MA-Token': 'bad'}).status_code == 401
    assert client.get('/api/v1/auth/sso/start').json()['code'] == 'SSO_NOT_AVAILABLE'


def test_register_gets_minimal_role_and_cabinet(client) -> None:
    body = {'name': 'Ирина Петрова', 'login': 'irina', 'email': 'irina@example.ru', 'password': 'Secret123', 'consent': True}
    assert client.post('/api/v1/auth/register', json={**body, 'password': 'short'}).status_code == 422
    assert client.post('/api/v1/auth/register', json={**body, 'password': 'onlyletters'}).json()['code'] == 'WEAK_PASSWORD'
    assert client.post('/api/v1/auth/register', json={**body, 'consent': False}).json()['code'] == 'CONSENT_REQUIRED'
    r = client.post('/api/v1/auth/register', json=body)
    assert r.status_code == 201, r.text
    assert r.json()['user']['role'] == 'expert'
    assert client.post('/api/v1/auth/register', json=body).json()['code'] == 'LOGIN_TAKEN'
    h = {'Authorization': f'Bearer {r.json()["access_token"]}'}
    assert client.get('/api/v1/programs', headers=h).json() == []  # без назначенных модулей ничего не видно
    assert client.post('/api/v1/programs', json={'request': 'Программа «Основы Git» на 16 часов'}, headers=h).status_code == 403
    assert client.get('/api/v1/admin/users', headers=h).status_code == 403
    assert client.put('/api/v1/auth/me', json={'title': 'Преподаватель'}, headers=h).json()['title'] == 'Преподаватель'
    assert client.put('/api/v1/auth/me/password', json={'current': 'bad', 'new': 'Newpass123'}, headers=h).status_code == 400
    assert client.put('/api/v1/auth/me/password', json={'current': 'Secret123', 'new': 'Newpass123'}, headers=h).status_code == 200
    _login(client, 'irina@example.ru', 'Newpass123')  # вход по почте


def test_admin_manages_users_but_not_programs(client) -> None:
    ha = _login(client, 'admin')
    users = client.get('/api/v1/admin/users', headers=ha).json()
    irina = next(u for u in users if u['login'] == 'irina')
    r = client.patch(f'/api/v1/admin/users/{irina["id"]}', json={'roles': ['methodist', 'expert']}, headers=ha)
    assert r.status_code == 200 and r.json()['roles'] == ['methodist', 'expert']
    hi = _login(client, 'irina', 'Newpass123')
    r = client.post('/api/v1/auth/switch-role', json={'role': 'expert'}, headers=hi)
    assert r.json()['user']['role'] == 'expert'
    assert client.post('/api/v1/auth/switch-role', json={'role': 'head'}, headers=hi).status_code == 403
    me = client.get('/api/v1/admin/users', headers=ha).json()
    admin_id = next(u['id'] for u in me if u['login'] == 'admin')
    assert client.patch(f'/api/v1/admin/users/{admin_id}', json={'roles': ['head']}, headers=ha).json()['code'] == 'LAST_ADMIN'
    r = client.post('/api/v1/admin/users', json={'login': 'petr', 'name': 'Пётр', 'password': 'Petr12345', 'roles': ['head']}, headers=ha)
    assert r.status_code == 201
    client.patch(f'/api/v1/admin/users/{r.json()["id"]}', json={'active': False}, headers=ha)
    assert client.post('/api/v1/auth/login', json={'login': 'petr', 'password': 'Petr12345'}).status_code == 401
    # Роли не пересекаются: программу создаёт методист, у администратора — 403
    r = client.post('/api/v1/programs', json={'request': 'Нужна программа «Основы Git» для разработчиков на 16 часов. Темы: ветки, слияние.'}, headers=ha)
    assert r.status_code == 403, r.text
    assert client.get('/api/v1/programs', headers=ha).status_code == 403
    assert client.get('/api/v1/reviews', headers=ha).status_code == 403
    assert client.get('/api/v1/admin/users', headers=_login(client, 'ahmed')).status_code == 403
    journal = client.get('/api/v1/admin/journal', headers=ha).json()
    assert any(e['action'] == 'register' for e in journal)


def test_settings_secret_masked_encrypted_and_applied(client) -> None:
    import asyncio

    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.db import SettingRow, sessionmaker

    ha = _login(client, 'admin')
    r = client.put('/api/v1/admin/settings', json={'values': {'llm_api_key': 'sk-test-1234567890abcd', 'llm_concurrency': 3}}, headers=ha)
    assert r.status_code == 200, r.text
    fields = {f['key']: f for f in r.json()['fields']}
    assert fields['llm_api_key']['value'] == '••••abcd' and fields['llm_api_key']['source'] == 'admin'
    assert 'sk-test' not in r.text
    assert get_settings().llm_api_key == 'sk-test-1234567890abcd' and get_settings().llm_concurrency == 3

    async def stored() -> str:
        async with sessionmaker()() as s:
            return (await s.execute(select(SettingRow).where(SettingRow.key == 'llm_api_key'))).scalar_one().value

    raw = asyncio.run(stored())
    assert raw.startswith('enc1:') and 'sk-test' not in raw
    # Маска в ответ не перезаписывает ключ; clear возвращает значение окружения
    client.put('/api/v1/admin/settings', json={'values': {'llm_api_key': '••••abcd'}}, headers=ha)
    assert get_settings().llm_api_key == 'sk-test-1234567890abcd'
    assert client.put('/api/v1/admin/settings', json={'values': {'llm_concurrency': 0}}, headers=ha).status_code == 400
    client.put('/api/v1/admin/settings', json={'clear': ['llm_api_key', 'llm_concurrency']}, headers=ha)
    assert get_settings().llm_api_key != 'sk-test-1234567890abcd' and get_settings().llm_concurrency == 2
    assert client.get('/api/v1/admin/settings', headers=_login(client, 'madina')).status_code == 403


def test_registration_and_demo_switches(client) -> None:
    ha = _login(client, 'admin')
    client.put('/api/v1/admin/settings', json={'values': {'registration_enabled': False}}, headers=ha)
    body = {'name': 'Гость', 'login': 'guest1', 'password': 'Guest12345', 'consent': True}
    assert client.post('/api/v1/auth/register', json=body).json()['code'] == 'REGISTRATION_CLOSED'
    client.put('/api/v1/admin/settings', json={'values': {'registration_enabled': True, 'registration_default_role': 'methodist'}}, headers=ha)
    assert client.post('/api/v1/auth/register', json=body).json()['user']['role'] == 'methodist'
    client.put('/api/v1/admin/settings', json={'values': {'demo_accounts_enabled': False}}, headers=ha)
    assert client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'demo'}).status_code == 401
    assert client.get('/api/v1/auth/config').json()['demo_accounts'] == []
    client.put('/api/v1/admin/settings', json={'clear': ['demo_accounts_enabled', 'registration_default_role']}, headers=ha)
    assert client.post('/api/v1/auth/login', json={'login': 'madina', 'password': 'demo'}).status_code == 200


def test_skill_override_and_reset(client) -> None:
    from app.skills.base import load_skills

    ha = _login(client, 'admin')
    skills = client.get('/api/v1/admin/skills', headers=ha).json()
    assert {'intake', 'skeleton', 'content'} <= {s['name'] for s in skills}
    r = client.put('/api/v1/admin/skills/skeleton', json={'temperature': 0.1, 'timeout_s': 90}, headers=ha)
    assert r.status_code == 200 and r.json()['overridden'] == ['temperature', 'timeout_s']
    assert load_skills()['skeleton'].temperature == 0.1
    assert client.put('/api/v1/admin/skills/skeleton', json={'temperature': 3}, headers=ha).status_code == 400
    r = client.put('/api/v1/admin/skills/skeleton', json={'reset': True}, headers=ha)
    assert r.json()['overridden'] == [] and load_skills()['skeleton'].temperature == r.json()['defaults']['temperature']
