"""Учётные записи: хранение в таблице users, кэш в памяти для проверок прав на каждом запросе."""

from __future__ import annotations

import re
import secrets
from typing import Any

from sqlalchemy import select

from app.core.db import UserRow, sessionmaker
from app.core.errors import BadRequest, Conflict, NotFound
from app.core.security import DEMO, ROLES, User, hash_password, set_users, users

LOGIN_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{2,31}$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
ASSIGNABLE = ('methodist', 'expert', 'head', 'admin')


def check_password(pw: str) -> None:
    """Пароль не короче 8 символов, хотя бы одна буква и одна цифра."""
    if len(pw) < 8 or not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        raise BadRequest('Пароль: не меньше 8 символов, хотя бы одна буква и одна цифра', code='WEAK_PASSWORD')


def _to_user(r: UserRow) -> User:
    return User(r.id, r.name, tuple(r.roles or ()), r.password_hash, r.title or '', r.login, r.email or '', r.source, bool(r.active))


async def load_users() -> dict[str, User]:
    """Создаёт демо-учётки при первом запуске и обновляет кэш из базы."""
    async with sessionmaker()() as s:
        rows = {r.id: r for r in (await s.execute(select(UserRow))).scalars()}
        pw = None
        for uid, login, name, roles, title in DEMO:
            if uid not in rows:
                pw = pw or hash_password('demo')
                s.add(UserRow(id=uid, login=login, name=name, roles=list(roles), title=title, password_hash=pw, source='demo'))
        await s.commit()
        items = {r.id: _to_user(r) for r in (await s.execute(select(UserRow))).scalars()}
    set_users(items)
    return items


def _validate(login: str | None = None, email: str | None = None, roles: list[str] | None = None, exclude: str = '') -> None:
    if login is not None:
        if not LOGIN_RE.match(login):
            raise BadRequest('Логин: 3–32 символа, латиница в нижнем регистре, цифры, точка, дефис или подчёркивание', code='BAD_LOGIN')
        if any(u.login.lower() == login and u.id != exclude for u in users().values()):
            raise Conflict('Такой логин уже занят', code='LOGIN_TAKEN')
    if email:
        if not EMAIL_RE.match(email):
            raise BadRequest('Некорректный адрес почты', code='BAD_EMAIL')
        if any(u.email.lower() == email.lower() and u.id != exclude for u in users().values()):
            raise Conflict('Пользователь с такой почтой уже есть', code='EMAIL_TAKEN')
    if roles is not None:
        if not roles:
            raise BadRequest('Нужна хотя бы одна роль')
        if bad := [r for r in roles if r not in ROLES]:
            raise BadRequest(f'Неизвестные роли: {", ".join(bad)}')


async def create_user(login: str, name: str, password: str, roles: list[str], email: str = '', title: str = '') -> User:
    login = login.strip().lower()
    _validate(login, email.strip(), roles)
    check_password(password)
    uid = 'u-' + secrets.token_hex(6)
    async with sessionmaker()() as s:
        s.add(UserRow(id=uid, login=login, name=name.strip(), email=email.strip(), title=title.strip(), roles=roles,
                      password_hash=hash_password(password), source='local'))
        await s.commit()
    await load_users()
    return users()[uid]


async def update_user(uid: str, changes: dict[str, Any]) -> User:
    """Меняет поля учётной записи; пароль приходит открытым и сохраняется только хешем bcrypt."""
    if uid not in users():
        raise NotFound('Пользователь не найден')
    _validate(changes.get('login'), changes.get('email'), changes.get('roles'), exclude=uid)
    if 'roles' in changes or changes.get('active') is False:
        roles = changes.get('roles', list(users()[uid].roles))
        active = changes.get('active', users()[uid].active)
        others = [u for u in users().values() if u.id != uid and 'admin' in u.roles and u.active]
        if not others and ('admin' not in roles or not active):
            raise Conflict('Нельзя убрать последнего активного администратора', code='LAST_ADMIN')
    async with sessionmaker()() as s:
        row = await s.get(UserRow, uid)
        assert row is not None
        for k in ('login', 'name', 'email', 'title', 'roles'):
            if k in changes and changes[k] is not None:
                setattr(row, k, changes[k].strip() if isinstance(changes[k], str) else changes[k])
        if 'active' in changes:
            row.active = int(bool(changes['active']))
        if changes.get('password'):
            check_password(changes['password'])
            row.password_hash = hash_password(changes['password'])
        await s.commit()
    await load_users()
    return users()[uid]
