"""Токены и лимиты по ТЗ 4.11: доступ 30 мин и обновление 30 дней, токены API от администратора, 30 программ в час, переменные таблицы 26."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import jwt
import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

REQ = 'Программа повышения квалификации «Основы Python» на 16 часов для аналитиков, очно, итоговая аттестация — тест.'


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _login(client, login: str, **kw) -> dict:
    r = client.post('/api/v1/auth/login', json={'login': login, 'password': 'demo', **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _claims(token: str) -> dict:
    from app.core.config import get_settings

    s = get_settings()
    return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])


def test_access_30_min_and_refresh_30_days(client) -> None:
    """SPEC-AUTH-25: вход, регистрация и смена роли выдают access_token на 30 минут (typ=access) и refresh_token на 30 дней (typ=refresh)."""
    from app.core.config import Settings

    assert Settings(_env_file=None).access_token_expire_minutes == 30 and Settings(_env_file=None).refresh_token_expire_days == 30
    j = _login(client, 'madina')
    a, r = _claims(j['access_token']), _claims(j['refresh_token'])
    now = datetime.now(tz=UTC).timestamp()
    assert a['typ'] == 'access' and 29 * 60 < a['exp'] - now <= 30 * 60
    assert r['typ'] == 'refresh' and 29 * 86400 < r['exp'] - now <= 30 * 86400
    assert j['token_type'] == 'bearer' and j['expires_in'] == 1800
    sw = client.post('/api/v1/auth/switch-role', json={'role': 'methodist'}, headers={'Authorization': f'Bearer {_login(client, "api")["access_token"]}'}).json()
    assert sw['refresh_token'] and sw['user']['role'] == 'methodist'
    reg = client.post('/api/v1/auth/register', json={'name': 'Пётр Иванов', 'login': 'petr.i', 'password': 'Secret123', 'consent': True}).json()
    assert _claims(reg['refresh_token'])['typ'] == 'refresh'
    # старые клиенты: только access_token, без typ (выпущенные до обновления) — работают
    from app.core.config import get_settings

    s = get_settings()
    legacy = jwt.encode({'sub': 'u-madina', 'role': 'methodist', 'exp': now + 600}, s.secret_key, algorithm=s.jwt_algorithm)
    assert client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {legacy}'}).status_code == 200


def test_refresh_endpoint_and_token_types(client) -> None:
    """SPEC-AUTH-26: POST /auth/refresh меняет токен обновления на новую пару; токен доступа не обновляет сессию, токен обновления не даёт доступа к API, отключённая учётка не обновляется."""
    j = _login(client, 'madina')
    r = client.post('/api/v1/auth/refresh', json={'refresh_token': j['refresh_token']})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new['user']['login'] == 'madina' and new['user']['role'] == 'methodist'
    assert new['refresh_token'] != j['refresh_token']
    assert client.get('/api/v1/auth/me', headers={'X-MA-Token': new['access_token']}).status_code == 200
    # типы токенов не взаимозаменяемы
    assert client.post('/api/v1/auth/refresh', json={'refresh_token': j['access_token']}).status_code == 401
    me = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {j["refresh_token"]}'})
    assert me.status_code == 401 and 'обновления' in me.json()['message_ru']
    assert client.post('/api/v1/auth/refresh', json={'refresh_token': 'not-a-jwt-token'}).status_code == 401
    # отключённый пользователь не продлевает вход
    adm = {'X-MA-Token': _login(client, 'admin')['access_token']}
    u = client.post('/api/v1/admin/users', json={'login': 'refresh.u', 'name': 'Проверка', 'password': 'Secret123', 'roles': ['expert']}, headers=adm).json()
    rt = client.post('/api/v1/auth/login', json={'login': 'refresh.u', 'password': 'Secret123'}).json()['refresh_token']
    assert client.patch(f'/api/v1/admin/users/{u["id"]}', json={'active': False}, headers=adm).status_code == 200
    assert client.post('/api/v1/auth/refresh', json={'refresh_token': rt}).status_code == 401


def test_admin_issues_lists_and_revokes_api_tokens(client) -> None:
    """SPEC-AUTH-27, SPEC-AUTH-28: администратор выдаёт токен API (значение один раз, в базе только хеш), видит список без секретов и отзывает; отозванный токен получает 401, остальным ролям методы недоступны."""
    from app.core.db import ApiTokenRow, sessionmaker

    adm = {'X-MA-Token': _login(client, 'admin')['access_token']}
    meth = {'X-MA-Token': _login(client, 'madina')['access_token']}
    assert client.post('/api/v1/admin/api-tokens', json={'name': 'x'}, headers=meth).status_code == 403
    assert client.get('/api/v1/admin/api-tokens').status_code in (401, 403)
    r = client.post('/api/v1/admin/api-tokens', json={'name': 'Автопрогон жюри', 'ttl_days': 7}, headers=adm)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t['token'].startswith('ma_') and t['user_id'] == 'u-api' and t['role'] == 'api' and t['active']
    assert t['expires_at'] > t['created_at'] and t['prefix'] == t['token'][:10]
    h = {'Authorization': f'Bearer {t["token"]}'}
    assert client.get('/api/v1/programs', headers=h).status_code == 200
    # токен API: те же права роли — api не входит в администрирование
    assert client.get('/api/v1/admin/users', headers=h).status_code == 403
    lst = client.get('/api/v1/admin/api-tokens', headers=adm).json()
    mine = next(x for x in lst if x['id'] == t['id'])
    assert 'token' not in mine and t['token'] not in str(lst) and mine['user_name'] == 'API-клиент' and mine['revoked_at'] is None

    async def stored() -> str:
        async with sessionmaker()() as s:
            return (await s.get(ApiTokenRow, t['id'])).token_hash

    assert client.portal.call(stored) not in ('', t['token']) and t['token'] not in client.portal.call(stored)
    # токен методиста с ролью из её ролей; чужая роль и неизвестный пользователь — ошибки
    tm = client.post('/api/v1/admin/api-tokens', json={'user_id': 'u-madina', 'name': 'LMS'}, headers=adm).json()
    assert tm['role'] == 'methodist'
    assert client.post('/api/v1/admin/api-tokens', json={'user_id': 'u-madina', 'role': 'admin'}, headers=adm).status_code == 400
    assert client.post('/api/v1/admin/api-tokens', json={'user_id': 'u-nobody'}, headers=adm).status_code == 404
    assert client.post('/api/v1/admin/api-tokens', json={'ttl_days': 0}, headers=adm).status_code == 422
    # отзыв: сразу 401, повторный отзыв не меняет дату, неизвестный id — 404
    d = client.delete(f'/api/v1/admin/api-tokens/{t["id"]}', headers=adm)
    assert d.status_code == 200 and d.json()['revoked_at'] and not d.json()['active']
    r401 = client.get('/api/v1/programs', headers=h)
    assert r401.status_code == 401 and 'отозван' in r401.json()['message_ru']
    assert client.delete(f'/api/v1/admin/api-tokens/{t["id"]}', headers=adm).json()['revoked_at'] == d.json()['revoked_at']
    assert client.delete('/api/v1/admin/api-tokens/tok-none', headers=adm).status_code == 404
    assert client.get('/api/v1/programs', headers={'Authorization': 'Bearer ma_unknown'}).status_code == 401
    j = client.get('/api/v1/admin/journal', headers=adm).json()
    assert {'api_token_issue', 'api_token_revoke'} <= {x['action'] for x in j} and t['token'] not in str(j)


def test_expired_api_token_rejected(client) -> None:
    """SPEC-AUTH-28: токен API с истёкшим сроком получает 401."""
    from app.core.db import ApiTokenRow, sessionmaker

    adm = {'X-MA-Token': _login(client, 'admin')['access_token']}
    t = client.post('/api/v1/admin/api-tokens', json={'name': 'короткий', 'ttl_days': 1}, headers=adm).json()

    async def expire() -> None:
        async with sessionmaker()() as s:
            (await s.get(ApiTokenRow, t['id'])).expires_at = '2020-01-01T00:00:00+00:00'
            await s.commit()

    client.portal.call(expire)
    assert client.get('/api/v1/programs', headers={'Authorization': f'Bearer {t["token"]}'}).status_code == 401
    assert next(x for x in client.get('/api/v1/admin/api-tokens', headers=adm).json() if x['id'] == t['id'])['active'] is False


def test_program_creation_limit_per_user(client, monkeypatch) -> None:
    """SPEC-AUTH-29: не больше programs_per_hour (30) новых программ в час на пользователя — дальше 429 RATE_LIMIT с message_ru; у роли api свой лимит api_programs_per_hour; другие пользователи не затронуты."""
    from app.core import security
    from app.core.config import Settings, get_settings

    assert Settings(_env_file=None).programs_per_hour == 30 and Settings(_env_file=None).api_programs_per_hour == 30
    s = get_settings()
    monkeypatch.setattr(s, 'programs_per_hour', 2)
    monkeypatch.setattr(s, 'api_programs_per_hour', 1)
    security._program_runs.clear()
    try:
        mh = {'X-MA-Token': _login(client, 'madina')['access_token']}
        for _ in range(2):
            assert client.post('/api/v1/programs', json={'request': REQ}, headers=mh).status_code == 200
        r = client.post('/api/v1/programs', json={'request': REQ}, headers=mh)
        assert r.status_code == 429 and r.json()['code'] == 'RATE_LIMIT' and '2 новых программ в час' in r.json()['message_ru']
        assert client.post('/api/v1/programs/upload', data={'text': REQ}, headers=mh).status_code == 429
        ah = {'Authorization': f'Bearer {_login(client, "api")["access_token"]}'}
        assert client.post('/api/v1/programs', json={'request': REQ}, headers=ah).status_code == 200
        assert client.post('/api/v1/programs', json={'request': REQ}, headers=ah).status_code == 429
        # аноним ограничен по адресу (anon_runs_per_hour), а не этим лимитом
        security.check_program_rate(security._anonymous_api())
    finally:
        security._program_runs.clear()


def test_env_settings_table_26() -> None:
    """SPEC-API-29: переменные таблицы 26 читаются из окружения: SANDBOX_TIMEOUT_S, SANDBOX_MEMORY_MB, а также зарезервированные LLM_MODEL_RERANK и REDIS_URL (по умолчанию пустые)."""
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert (s.sandbox_timeout_s, s.sandbox_memory_mb, s.llm_model_rerank, s.redis_url) == (10, 512, '', '')
    env = {'SANDBOX_TIMEOUT_S': '5', 'SANDBOX_MEMORY_MB': '1024', 'LLM_MODEL_RERANK': 'BAAI/bge-reranker-v2-m3', 'REDIS_URL': 'redis://localhost:6379/0',
           'ACCESS_TOKEN_EXPIRE_MINUTES': '45', 'PROGRAMS_PER_HOUR': '50'}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        s = Settings(_env_file=None)
        assert (s.sandbox_timeout_s, s.sandbox_memory_mb, s.access_token_expire_minutes, s.programs_per_hour) == (5, 1024, 45, 50)
        assert s.llm_model_rerank == 'BAAI/bge-reranker-v2-m3' and s.redis_url.startswith('redis://')
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
