"""Токены API интеграций (ТЗ, 4.1, US-22): администратор выдаёт и отзывает; в базе только SHA-256 токена.

Токен показывается один раз при выдаче. Отозванный, просроченный токен или токен отключённой учётки получает 401.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.db import ApiTokenRow, now_iso, sessionmaker
from app.core.errors import BadRequest, NotFound
from app.core.security import API_TOKEN_PREFIX, users


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _active(r: ApiTokenRow) -> bool:
    return not r.revoked_at and datetime.fromisoformat(r.expires_at) > datetime.now(tz=UTC)


def public(r: ApiTokenRow) -> dict[str, Any]:
    """Описание токена без секрета: кто владелец, когда выдан, до какого срока, отозван ли."""
    u = users().get(r.user_id)
    return {'id': r.id, 'name': r.name, 'user_id': r.user_id, 'user_name': u.name if u else r.user_id, 'role': r.role,
            'prefix': r.prefix, 'created_by': r.created_by, 'created_at': r.created_at, 'expires_at': r.expires_at,
            'revoked_at': r.revoked_at or None, 'active': _active(r)}


async def issue(user_id: str, name: str, role: str | None, ttl_days: int, actor: str) -> dict[str, Any]:
    """Новый токен для учётки: роль — из её ролей (по умолчанию api, если есть). Секрет возвращается только здесь."""
    u = users().get(user_id)
    if u is None:
        raise NotFound('Пользователь не найден')
    if not u.active:
        raise BadRequest('Учётная запись отключена: токен для неё не выдаётся', code='USER_INACTIVE')
    role = role or ('api' if 'api' in u.roles else u.roles[0])
    if role not in u.roles:
        raise BadRequest(f'У пользователя нет роли «{role}»', details={'roles': list(u.roles)})
    token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiTokenRow(id='tok-' + secrets.token_hex(6), name=name.strip() or f'Токен {u.login}', user_id=u.id, role=role,
                      token_hash=_hash(token), prefix=token[:10], created_by=actor, created_at=now_iso(),
                      expires_at=(datetime.now(tz=UTC) + timedelta(days=ttl_days)).isoformat(timespec='seconds'))
    async with sessionmaker()() as s:
        s.add(row)
        await s.commit()
    return {**public(row), 'token': token}


async def list_tokens() -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(ApiTokenRow).order_by(ApiTokenRow.created_at.desc()))).scalars().all()
    return [public(r) for r in rows]


async def revoke(token_id: str) -> dict[str, Any]:
    """Отзыв действует сразу: следующий запрос с этим токеном получает 401. Повторный отзыв ничего не меняет."""
    async with sessionmaker()() as s:
        row = await s.get(ApiTokenRow, token_id)
        if row is None:
            raise NotFound('Токен не найден')
        if not row.revoked_at:
            row.revoked_at = now_iso()
            await s.commit()
    return public(row)


async def lookup(token: str) -> ApiTokenRow | None:
    """Действующий токен по его значению или None (неизвестен, отозван, истёк)."""
    async with sessionmaker()() as s:
        row = (await s.execute(select(ApiTokenRow).where(ApiTokenRow.token_hash == _hash(token)))).scalar_one_or_none()
    return row if row is not None and _active(row) else None
