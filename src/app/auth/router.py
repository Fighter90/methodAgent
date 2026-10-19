"""Вход, регистрация, личный кабинет и администрирование (пользователи, настройки, навыки агента)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import service, tokens
from app.core import runtime
from app.core.config import get_settings
from app.core.errors import (
    BadRequest,
    ForbiddenRole,
    NotFound,
    RateLimited,
    Unauthorized,
)
from app.core.security import (
    DEMO,
    Principal,
    _client_ip,
    by_login,
    create_token,
    current_principal,
    decode_token,
    principal_for,
    require,
    users,
    verify_password,
)
from app.programs import service as svc

auth = APIRouter(prefix='/auth', tags=['auth'])
admin = APIRouter(prefix='/admin', tags=['admin'])


def _signed_in(p: Principal = Depends(current_principal)) -> Principal:
    if p.anonymous:
        raise Unauthorized('Нужен вход')
    return p


def _session(user_id: str, role: str) -> dict[str, Any]:
    """Токен доступа (30 мин) и токен обновления (30 дней); старые клиенты читают только access_token."""
    u = users()[user_id]
    return {'access_token': create_token(u.id, role), 'refresh_token': create_token(u.id, role, 'refresh'), 'token_type': 'bearer',
            'expires_in': get_settings().access_token_expire_minutes * 60, 'user': {**u.public(), 'role': role}}


class LoginIn(BaseModel):
    login: str = Field('', max_length=200, description='Логин или почта')
    user_id: str = Field('', max_length=64, description='Для совместимости: id пользователя (u-madina)')
    password: str = Field('demo', max_length=200)
    role: str | None = None


_login_failures: dict[str, deque[float]] = defaultdict(deque)


@auth.post('/login', summary='Вход по логину (или почте) и паролю: токен с ролью')
async def login(body: LoginIn, request: Request) -> dict[str, Any]:
    # Подбор пароля: не больше login_failures_per_minute неудачных попыток в минуту с одного адреса (ТЗ, 4.11)
    fails = _login_failures[_client_ip(request)]
    now = time.monotonic()
    while fails and now - fails[0] > 60:
        fails.popleft()
    if len(fails) >= get_settings().login_failures_per_minute:
        raise RateLimited('Слишком много неудачных попыток входа с этого адреса. Повторите через минуту.')
    key = body.login or body.user_id
    u = by_login(key) or next((x for x in users().values() if x.email and x.email.lower() == key.strip().lower()), None)
    if u is None or not verify_password(body.password, u.password_hash):
        fails.append(now)
        raise Unauthorized('Неверный логин или пароль')
    if not u.active:
        raise Unauthorized('Учётная запись отключена администратором')
    if u.source == 'demo' and u.id not in ('u-api', 'u-admin') and not get_settings().demo_accounts_enabled:
        raise Unauthorized('Демо-учётки отключены администратором')
    role = body.role or u.roles[0]
    if role not in u.roles:
        raise Unauthorized('У пользователя нет такой роли')
    return _session(u.id, role)


_reg_attempts: dict[str, deque[float]] = defaultdict(deque)


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    login: str = Field(min_length=3, max_length=32)
    email: str = Field('', max_length=200)
    password: str = Field(min_length=8, max_length=200)
    consent: bool = Field(False, description='Согласие на обработку персональных данных (152-ФЗ)')


@auth.post('/register', status_code=201, summary='Регистрация: роль по умолчанию с минимальными правами (настраивает администратор)')
async def register(body: RegisterIn, request: Request) -> dict[str, Any]:
    s = get_settings()
    if not s.registration_enabled:
        raise ForbiddenRole('Регистрация закрыта администратором', code='REGISTRATION_CLOSED')
    if not body.consent:
        raise BadRequest('Нужно согласие на обработку персональных данных', code='CONSENT_REQUIRED')
    q = _reg_attempts[_client_ip(request)]
    now = time.monotonic()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= 10:
        raise RateLimited('Слишком много регистраций с одного адреса, повторите позже')
    q.append(now)
    role = s.registration_default_role if s.registration_default_role in service.ASSIGNABLE[:3] else 'expert'
    u = await service.create_user(body.login, body.name, body.password, [role], body.email)
    await svc.log_event('org', u.id, 'register', f'Регистрация: {u.name} ({u.login}), роль {role}', version=0)
    return _session(u.id, role)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4000)


@auth.post('/refresh', summary='Новая пара токенов по токену обновления (токен доступа сюда не подходит)')
async def refresh(body: RefreshIn) -> dict[str, Any]:
    payload = decode_token(body.refresh_token, 'refresh')
    p = principal_for(payload.get('sub', ''), payload.get('role', ''))
    return _session(p.user_id, p.role)


@auth.get('/config', summary='Что показывать на форме входа: демо-учётки, регистрация, SSO')
async def auth_config() -> dict[str, Any]:
    s = get_settings()
    demo = [{'login': login, 'name': name, 'role': roles[0], 'title': title} for _, login, name, roles, title in DEMO] \
        if s.demo_accounts_enabled else []
    return {
        'demo_accounts': demo,
        'demo_password': 'demo' if demo else '',
        'registration_enabled': s.registration_enabled,
        'registration_default_role': s.registration_default_role,
        'sso': {'enabled': s.sso_enabled, 'provider': s.sso_provider, 'display_name': s.sso_display_name,
                'configured': bool(s.sso_issuer_url and s.sso_client_id), 'available': False},
    }


@auth.get('/sso/start', summary='Вход через SSO (OIDC/SAML): заготовка, протокол подключается в следующей версии')
async def sso_start() -> dict[str, Any]:
    raise BadRequest('Вход через SSO предусмотрен, но ещё не подключён. Войдите по логину и паролю.', code='SSO_NOT_AVAILABLE')


@auth.get('/users', summary='Демо-пользователи для переключателя ролей')
async def demo_users() -> list[dict[str, Any]]:
    if not get_settings().demo_accounts_enabled:
        return []
    return [{'id': u.id, 'login': u.login, 'name': u.name, 'roles': list(u.roles), 'title': u.title} for u in users().values() if u.source == 'demo']


@auth.get('/me', summary='Личный кабинет: данные текущего пользователя')
async def me(p: Principal = Depends(_signed_in)) -> dict[str, Any]:
    return {**users()[p.user_id].public(), 'role': p.role}


class MeIn(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    email: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=200)


@auth.put('/me', summary='Изменить имя, почту и должность')
async def update_me(body: MeIn, p: Principal = Depends(_signed_in)) -> dict[str, Any]:
    if users()[p.user_id].source == 'demo':
        raise ForbiddenRole('Демо-учётку меняет только администратор')
    u = await service.update_user(p.user_id, body.model_dump(exclude_none=True))
    return {**u.public(), 'role': p.role}


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=8, max_length=200)


@auth.put('/me/password', summary='Сменить пароль')
async def change_password(body: PasswordIn, p: Principal = Depends(_signed_in)) -> dict[str, str]:
    u = users()[p.user_id]
    if u.source == 'demo':
        raise ForbiddenRole('Пароль демо-учётки меняет только администратор')
    if not verify_password(body.current, u.password_hash):
        raise BadRequest('Текущий пароль указан неверно', code='WRONG_PASSWORD')
    await service.update_user(p.user_id, {'password': body.new})
    await svc.log_event('org', p.user_id, 'password', 'Пароль изменён', version=0)
    return {'status': 'ok'}


class SwitchIn(BaseModel):
    role: str


@auth.post('/switch-role', summary='Сменить роль в пределах ролей пользователя')
async def switch_role(body: SwitchIn, p: Principal = Depends(_signed_in)) -> dict[str, Any]:
    if body.role not in users()[p.user_id].roles:
        raise ForbiddenRole('У пользователя нет такой роли')
    return _session(p.user_id, body.role)


# --- Администрирование ---
@admin.get('/users', summary='Пользователи и их роли (администратор)')
async def list_users(p: Principal = Depends(require('admin'))) -> list[dict[str, Any]]:
    return [u.public() for u in users().values()]


class UserIn(BaseModel):
    login: str = Field(min_length=3, max_length=32)
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    roles: list[str] = Field(default_factory=lambda: ['expert'])
    email: str = Field('', max_length=200)
    title: str = Field('', max_length=200)


@admin.post('/users', status_code=201, summary='Создать пользователя (администратор)')
async def create_user(body: UserIn, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    u = await service.create_user(body.login, body.name, body.password, body.roles, body.email, body.title)
    await svc.log_event('org', p.user_id, 'user_create', f'{u.name} ({u.login}): {", ".join(u.roles)}', version=0)
    return u.public()


class UserPatch(BaseModel):
    login: str | None = Field(None, min_length=3, max_length=32)
    name: str | None = Field(None, min_length=2, max_length=120)
    email: str | None = Field(None, max_length=200)
    title: str | None = Field(None, max_length=200)
    roles: list[str] | None = None
    active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=200, description='Новый пароль (сброс администратором)')


@admin.patch('/users/{user_id}', summary='Изменить роли, данные, пароль или отключить пользователя (администратор)')
async def patch_user(user_id: str, body: UserPatch, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    if 'login' in changes:
        changes['login'] = changes['login'].strip().lower()
    u = await service.update_user(user_id, changes)
    shown = ', '.join(sorted(k if k != 'password' else 'пароль' for k in changes))
    await svc.log_event('org', p.user_id, 'user_update', f'{u.name} ({u.login}): {shown}', version=0)
    return u.public()


class ApiTokenIn(BaseModel):
    user_id: str = Field('u-api', max_length=64, description='Владелец токена; по умолчанию служебная учётка API-клиента')
    name: str = Field('', max_length=120, description='Назначение: «Автопрогон жюри», «LMS колледжа»')
    role: str | None = Field(None, description='Роль токена из ролей владельца; по умолчанию api, если она есть')
    ttl_days: int | None = Field(None, ge=1, le=365, description='Срок действия, дней (по умолчанию api_token_default_days)')


@admin.get('/api-tokens', summary='Токены API: владелец, срок, отозван ли (без секретов)')
async def list_api_tokens(p: Principal = Depends(require('admin'))) -> list[dict[str, Any]]:
    return await tokens.list_tokens()


@admin.post('/api-tokens', status_code=201, summary='Выдать токен API (администратор); значение токена показывается один раз')
async def issue_api_token(body: ApiTokenIn, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    t = await tokens.issue(body.user_id, body.name, body.role, body.ttl_days or get_settings().api_token_default_days, p.user_id)
    await svc.log_event('org', p.user_id, 'api_token_issue', f'Выдан токен API «{t["name"]}» ({t["prefix"]}…) для {t["user_name"]}, роль {t["role"]}, до {t["expires_at"][:10]}', version=0)
    return t


@admin.delete('/api-tokens/{token_id}', summary='Отозвать токен API (администратор): дальше запросы с ним получают 401')
async def revoke_api_token(token_id: str, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    t = await tokens.revoke(token_id)
    await svc.log_event('org', p.user_id, 'api_token_revoke', f'Отозван токен API «{t["name"]}» ({t["prefix"]}…)', version=0)
    return t


@admin.get('/settings', summary='Настройки агента: ключи (маской), модели, лимиты, вход, SSO, почта')
async def get_settings_(p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    return {'groups': runtime.GROUPS, 'fields': runtime.describe()}


class SettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list, description='Вернуть значение из окружения')


@admin.put('/settings', summary='Изменить настройки агента (администратор); значения ключей в журнал не пишутся')
async def put_settings(body: SettingsIn, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    changed = await runtime.update(body.values, body.clear, p.user_id)
    if changed:
        await svc.log_event('org', p.user_id, 'settings', 'Изменены настройки: ' + ', '.join(runtime.BY_KEY[k].label for k in changed), version=0)
    return {'changed': changed, 'groups': runtime.GROUPS, 'fields': runtime.describe()}


@admin.get('/skills', summary='Навыки агента: параметры и инструкция модели')
async def get_skills(p: Principal = Depends(require('admin'))) -> list[dict[str, Any]]:
    from app.skills.base import EDITABLE, load_overrides, load_skills, original_skills

    ov, orig = load_overrides(), original_skills()
    return [{'name': k, 'description': v.description, 'model_role': v.model_role, 'instruction': v.instruction,
             **{f: getattr(v, f) for f in EDITABLE}, 'overridden': sorted(ov.get(k, {})),
             'defaults': {f: getattr(orig[k], f) for f in EDITABLE}} for k, v in load_skills().items()]


class SkillIn(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_s: float | None = None
    retries: int | None = None
    instruction: str | None = Field(None, max_length=20000)
    reset: bool = Field(False, description='Вернуть параметры из SKILL.md')


@admin.put('/skills/{name}', summary='Изменить параметры или инструкцию навыка (администратор)')
async def put_skill(name: str, body: SkillIn, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    from app.skills.base import EDITABLE, load_overrides, load_skills, save_overrides

    if name not in load_skills():
        raise NotFound('Навык не найден')
    data = load_overrides()
    if body.reset:
        data.pop(name, None)
    else:
        cur = data.get(name, {})
        for f, (typ, lo, hi) in EDITABLE.items():
            v = getattr(body, f)
            if v is not None:
                if not lo <= v <= hi:
                    raise BadRequest(f'{f}: допустимо от {lo:g} до {hi:g}')
                cur[f] = typ(v)
        if body.instruction is not None:
            if len(body.instruction.strip()) < 20:
                raise BadRequest('Инструкция модели слишком короткая')
            cur['instruction'] = body.instruction.strip()
        data[name] = cur
    save_overrides(data)
    await svc.log_event('org', p.user_id, 'skill', f'Навык {name}: ' + ('сброшен к SKILL.md' if body.reset else ', '.join(sorted(data[name]))), version=0)
    return next(s for s in await get_skills(p) if s['name'] == name)


@admin.get('/journal', summary='Журнал действий администратора и входа (регистрации, настройки, пользователи)')
async def admin_journal(p: Principal = Depends(require('admin'))) -> list[dict[str, Any]]:
    return await svc.events('org')
