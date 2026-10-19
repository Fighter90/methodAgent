"""Роли и токены: JWT с ролью, права проверяются на каждом методе (ТЗ, 4.1; NFR-10)."""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, Header, Request

from app.core.config import get_settings
from app.core.errors import ForbiddenRole, RateLimited, Unauthorized

ROLES = ('methodist', 'expert', 'head', 'admin', 'api')
API_TOKEN_PREFIX = 'ma_'  # токены API от администратора; JWT так не начинаются


@dataclass(frozen=True)
class User:
    id: str
    name: str
    roles: tuple[str, ...]
    password_hash: str
    title: str = ''
    login: str = ''
    email: str = ''
    source: str = 'demo'
    active: bool = True

    def public(self) -> dict[str, Any]:
        return {'id': self.id, 'login': self.login, 'name': self.name, 'roles': list(self.roles), 'title': self.title,
                'email': self.email, 'source': self.source, 'active': self.active}


DemoUser = User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# Демонстрационный профиль АЦР (ТЗ, 4.4.1): id, логин, имя, роли, должность
DEMO = (
    ('u-madina', 'madina', 'Мадина', ('methodist',), 'Методист'),
    ('u-timur', 'timur', 'Тимур А.', ('expert',), 'Эксперт-преподаватель'),
    ('u-olga', 'olga', 'Ольга К.', ('expert',), 'Эксперт-преподаватель'),
    ('u-ahmed', 'ahmed', 'Ахмед', ('head',), 'Руководитель учебного центра'),
    ('u-admin', 'admin', 'Администратор', ('admin',), 'Администратор профиля'),
    ('u-api', 'api', 'API-клиент', ('api', 'methodist'), 'Автопрогон'),
)


def _demo_users() -> dict[str, User]:
    pw = hash_password('demo')
    return {i: User(i, name, roles, pw, title, login) for i, login, name, roles, title in DEMO}


_USERS: dict[str, User] | None = None


def users() -> dict[str, User]:
    """Кэш учётных записей в памяти; источник — таблица users (load_users при старте и после каждого изменения)."""
    global _USERS
    if _USERS is None:
        _USERS = _demo_users()
    return _USERS


def set_users(items: dict[str, User]) -> None:
    global _USERS
    _USERS = items


def by_login(login: str) -> User | None:
    """Вход по логину или по id (автопрогон и старые клиенты передают user_id)."""
    key = login.strip().lower()
    return next((u for u in users().values() if u.login.lower() == key), None) or users().get(login.strip())


def create_token(user_id: str, role: str, typ: str = 'access') -> str:
    """Токен доступа (typ=access, access_token_expire_minutes) или обновления (typ=refresh, refresh_token_expire_days).

    Поле typ разводит токены: токеном обновления нельзя вызвать метод API, токеном доступа — обновить сессию."""
    s = get_settings()
    life = timedelta(days=s.refresh_token_expire_days) if typ == 'refresh' else timedelta(minutes=s.access_token_expire_minutes)
    payload: dict[str, Any] = {'sub': user_id, 'role': role, 'typ': typ, 'exp': datetime.now(tz=UTC) + life}
    if typ == 'refresh':
        payload['jti'] = secrets.token_hex(8)  # каждый токен обновления уникален
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


def decode_token(token: str, typ: str = 'access') -> dict[str, Any]:
    """Проверяет подпись, срок и тип; токены, выпущенные до появления typ, считаются токенами доступа."""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise Unauthorized('Токен недействителен или истёк') from exc
    if payload.get('typ', 'access') != typ:
        raise Unauthorized('Нужен токен обновления' if typ == 'refresh' else 'Токен обновления не даёт доступа к API: получите токен доступа (POST /api/v1/auth/refresh)')
    return payload


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    name: str
    anonymous: bool = False


def _anonymous_api() -> Principal:
    # Автопрогон организаторов вызывает единый эндпоинт без токена: роль api
    return Principal('u-api', 'api', 'API-клиент', anonymous=True)


_anon_runs: dict[str, deque[float]] = defaultdict(deque)
_program_runs: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get('x-forwarded-for', '')
    return fwd.split(',')[0].strip() or (request.client.host if request.client else 'unknown')


def _hit(log: dict[str, deque[float]], key: str, limit: int, period: float = 3600) -> bool:
    """Скользящее окно: True — лимит за period секунд исчерпан; иначе обращение учитывается и возвращается False."""
    q = log[key]
    now = time.monotonic()
    while q and now - q[0] > period:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _anonymous(request: Request) -> Principal:
    """Без токена: автопрогон POST /programs?mode=auto с лимитом частоты и чтение его же результатов; остальное — 401.

    Публичный адрес открыт всем, а дневной бюджет шлюза общий — поэтому запись и интерфейсные методы требуют токен.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return _anonymous_api()
    if request.method == 'POST' and request.url.path.rstrip('/').endswith('/programs') and request.query_params.get('mode') == 'auto':
        limit = get_settings().anon_runs_per_hour
        if _hit(_anon_runs, _client_ip(request), limit):
            raise RateLimited(f'Без токена — не больше {limit} автопрогонов в час с одного адреса. Войдите или повторите позже.')
        return _anonymous_api()
    raise Unauthorized('Нужен вход: заголовок Authorization: Bearer <токен> (POST /api/v1/auth/login)')


def check_program_rate(p: Principal) -> None:
    """ТЗ, 4.11: не больше programs_per_hour новых программ в час на пользователя, для роли api — api_programs_per_hour.

    Аноним уже ограничен по адресу (anon_runs_per_hour). Счётчики в памяти процесса, как и лимит входа."""
    if p.anonymous:
        return
    s = get_settings()
    limit = s.api_programs_per_hour if p.role == 'api' else s.programs_per_hour
    if _hit(_program_runs, p.user_id, limit):
        raise RateLimited(f'Не больше {limit} новых программ в час на пользователя. Повторите позже.', details={'limit': limit, 'period_s': 3600})


def principal_for(user_id: str, role: str) -> Principal:
    """Учётка из токена: существует, активна, роль среди её ролей, демо-учётки не отключены."""
    user = users().get(user_id)
    if user is None or role not in user.roles or not user.active:
        raise Unauthorized('Токен недействителен')
    if user.source == 'demo' and user.id not in ('u-api', 'u-admin') and not get_settings().demo_accounts_enabled:
        raise Unauthorized('Демо-учётки отключены администратором')
    return Principal(user.id, role, user.name)


async def current_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_ma_token: str | None = Header(default=None),
) -> Principal:
    # Интерфейс шлёт токен в X-MA-Token: прокси хаба перехватывает любой запрос с Authorization и уводит его на свой вход.
    # Authorization: Bearer остаётся для API-клиентов и автопрогона, которые ходят мимо хаба.
    if x_ma_token:
        token = x_ma_token.strip()
    elif authorization:
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer' or not token:
            raise Unauthorized('Нужен заголовок Authorization: Bearer <токен>')
    else:
        return _anonymous(request)
    if token.startswith(API_TOKEN_PREFIX):
        from app.auth.tokens import lookup

        row = await lookup(token)
        if row is None:
            raise Unauthorized('Токен API недействителен, отозван или истёк')
        return principal_for(row.user_id, row.role)
    payload = decode_token(token)
    return principal_for(payload.get('sub', ''), payload.get('role', ''))


def require(*roles: str):
    """Зависимость FastAPI: действие доступно только перечисленным ролям, иначе 403.

    Роли не пересекаются: администратор ведёт пользователей, настройки агента и базу знаний,
    а программы создаёт методист, вычитывает эксперт, утверждает руководитель."""

    async def _dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles:
            raise ForbiddenRole(f'Роль «{p.role}» не может выполнить это действие', details={'allowed': list(roles)})
        return p

    return _dep
