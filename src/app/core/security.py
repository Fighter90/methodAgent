"""Роли и токены: JWT с ролью, права проверяются на каждом методе (ТЗ, 4.1; NFR-10)."""

from __future__ import annotations

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


def create_token(user_id: str, role: str) -> str:
    s = get_settings()
    payload: dict[str, Any] = {
        'sub': user_id,
        'role': role,
        'exp': datetime.now(tz=UTC) + timedelta(minutes=s.access_token_expire_minutes),
    }
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm)


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


def _client_ip(request: Request) -> str:
    fwd = request.headers.get('x-forwarded-for', '')
    return fwd.split(',')[0].strip() or (request.client.host if request.client else 'unknown')


def _anonymous(request: Request) -> Principal:
    """Без токена: автопрогон POST /programs?mode=auto с лимитом частоты и чтение его же результатов; остальное — 401.

    Публичный адрес открыт всем, а дневной бюджет шлюза общий — поэтому запись и интерфейсные методы требуют токен.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return _anonymous_api()
    if request.method == 'POST' and request.url.path.rstrip('/').endswith('/programs') and request.query_params.get('mode') == 'auto':
        limit = get_settings().anon_runs_per_hour
        q = _anon_runs[_client_ip(request)]
        now = time.monotonic()
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= limit:
            raise RateLimited(f'Без токена — не больше {limit} автопрогонов в час с одного адреса. Войдите или повторите позже.')
        q.append(now)
        return _anonymous_api()
    raise Unauthorized('Нужен вход: заголовок Authorization: Bearer <токен> (POST /api/v1/auth/login)')


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
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise Unauthorized('Токен недействителен или истёк') from exc
    user = users().get(payload.get('sub', ''))
    role = payload.get('role', '')
    if user is None or role not in user.roles or not user.active:
        raise Unauthorized('Токен недействителен')
    if user.source == 'demo' and user.id not in ('u-api', 'u-admin') and not s.demo_accounts_enabled:
        raise Unauthorized('Демо-учётки отключены администратором')
    return Principal(user.id, role, user.name)


def require(*roles: str):
    """Зависимость FastAPI: действие доступно только перечисленным ролям, иначе 403. Администратор управляет всем."""

    async def _dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles and p.role != 'admin':
            raise ForbiddenRole(f'Роль «{p.role}» не может выполнить это действие', details={'allowed': list(roles)})
        return p

    return _dep
