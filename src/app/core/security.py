"""Роли и токены: JWT с ролью, права проверяются на каждом методе (ТЗ, 4.1; NFR-10)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, Header

from app.core.config import get_settings
from app.core.errors import ForbiddenRole, Unauthorized

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


async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization:
        return _anonymous_api()
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
