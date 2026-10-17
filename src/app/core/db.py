"""Хранилище: SQLAlchemy 2 (async). SQLite на ВМ и в тестах, PostgreSQL — на стенде.

Программа хранится документом JSON (граф комплекта по подразделу 4.8) с версиями
и журналом событий; перезапуск сервиса не теряет состояние (NFR-08).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec='seconds')


class ProgramRow(Base):
    __tablename__ = 'programs'

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300), default='')
    status: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    doc: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VersionRow(Base):
    __tablename__ = 'program_versions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default='')
    doc: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventRow(Base):
    """Журнал событий: кто, что и когда изменил или утвердил (FR-58)."""

    __tablename__ = 'audit_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    program_id: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    node_id: Mapped[str] = mapped_column(String(64), default='')
    text: Mapped[str] = mapped_column(Text, default='')
    version: Mapped[int] = mapped_column(Integer, default=1)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRow(Base):
    __tablename__ = 'jobs'

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    program_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationRow(Base):
    __tablename__ = 'notifications'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    program_id: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    read: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    sessionmaker()
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session


async def max_version(session: AsyncSession, program_id: str) -> int:
    res = await session.execute(select(func.max(VersionRow.version)).where(VersionRow.program_id == program_id))
    return int(res.scalar() or 0)
