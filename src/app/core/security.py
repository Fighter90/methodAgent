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
class DemoUser:
    id: str
    name: str
    roles: tuple[str, ...]
    password_hash: str
    title: str = ''


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def _demo_users() -> dict[str, DemoUser]:
    """Демонстрационный профиль АЦР (ТЗ, 4.4.1): Мадина, Тимур, Ольга, Ахмед и сервисный API-клиент."""
    pw = hash_password('demo')
    return {
        'u-madina': DemoUser('u-madina', 'Мадина', ('methodist',), pw, 'Методист'),
        'u-timur': DemoUser('u-timur', 'Тимур А.', ('expert',), pw, 'Эксперт-преподаватель'),
        'u-olga': DemoUser('u-olga', 'Ольга К.', ('expert',), pw, 'Эксперт-преподаватель'),
        'u-ahmed': DemoUser('u-ahmed', 'Ахмед', ('head',), pw, 'Руководитель учебного центра'),
        'u-admin': DemoUser('u-admin', 'Администратор', ('admin',), pw, 'Администратор профиля'),
        'u-api': DemoUser('u-api', 'API-клиент', ('api', 'methodist'), pw, 'Автопрогон'),
    }


_USERS: dict[str, DemoUser] | None = None


def users() -> dict[str, DemoUser]:
    global _USERS
    if _USERS is None:
        _USERS = _demo_users()
    return _USERS


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


def _anonymous_api() -> Principal:
    # Автопрогон организаторов вызывает единый эндпоинт без токена: роль api
    return Principal('u-api', 'api', 'API-клиент')


_anon_runs: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get('x-forwarded-for', '')
    return fwd.split(',')[0].strip() or (request.client.host if request.client else 'unknown')


def _anonymous(request: Request) -> Principal:
    """Без токена: чтение и автопрогон POST /programs?mode=auto с лимитом частоты; остальное — только после входа.

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


async def current_principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    if not authorization:
        return _anonymous(request)
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise Unauthorized('Нужен заголовок Authorization: Bearer <токен>')
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise Unauthorized('Токен недействителен или истёк') from exc
    user = users().get(payload.get('sub', ''))
    role = payload.get('role', '')
    if user is None or role not in user.roles:
        raise Unauthorized('Токен недействителен')
    return Principal(user.id, role, user.name)


def require(*roles: str):
    """Зависимость FastAPI: действие доступно только перечисленным ролям, иначе 403."""

    async def _dep(p: Principal = Depends(current_principal)) -> Principal:
        if p.role not in roles:
            raise ForbiddenRole(f'Роль «{p.role}» не может выполнить это действие', details={'allowed': list(roles)})
        return p

    return _dep
