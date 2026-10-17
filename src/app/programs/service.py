"""Сервис программ: загрузка и сохранение документа, версии, журнал, задания (job_id)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.core.db import EventRow, JobRow, NotificationRow, ProgramRow, VersionRow, max_version, now_iso, sessionmaker
from app.core.errors import NotFound
from app.programs.schemas import ProgramDoc

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def new_id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:10]}'


async def load(program_id: str) -> ProgramDoc:
    async with sessionmaker()() as s:
        row = await s.get(ProgramRow, program_id)
        if row is None:
            raise NotFound('Программа не найдена')
        return ProgramDoc.model_validate(row.doc)


async def save(doc: ProgramDoc, owner: str = 'u-madina', *, reason: str = '', snapshot: bool = False) -> None:
    doc.updated_at = now_iso()
    async with sessionmaker()() as s:
        row = await s.get(ProgramRow, doc.id)
        if snapshot:
            doc.version = max(doc.version, await max_version(s, doc.id)) + 1
        data = doc.model_dump(mode='json')
        if row is None:
            s.add(ProgramRow(id=doc.id, owner=owner, title=doc.title, status=doc.status.value, version=doc.version, doc=data))
        else:
            row.doc, row.status, row.title, row.version = data, doc.status.value, doc.title, doc.version
        if snapshot:
            s.add(VersionRow(program_id=doc.id, version=doc.version, reason=reason, doc=data))
        await s.commit()


async def log_event(program_id: str, actor: str, action: str, text: str = '', node_id: str = '', version: int = 1) -> None:
    async with sessionmaker()() as s:
        s.add(EventRow(program_id=program_id, actor=actor, action=action, text=text[:2000], node_id=node_id, version=version))
        await s.commit()


async def notify(user_id: str, program_id: str, text: str) -> None:
    async with sessionmaker()() as s:
        s.add(NotificationRow(user_id=user_id, program_id=program_id, text=text))
        await s.commit()


async def notifications(user_id: str) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(NotificationRow).where(NotificationRow.user_id == user_id).order_by(NotificationRow.id.desc()).limit(30))).scalars()
        return [{'id': r.id, 'program_id': r.program_id, 'text': r.text, 'read': bool(r.read), 'at': r.at.isoformat() if r.at else ''} for r in rows]


async def events(program_id: str) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(EventRow).where(EventRow.program_id == program_id).order_by(EventRow.id.desc()).limit(200))).scalars()
        return [{'actor': r.actor, 'action': r.action, 'text': r.text, 'node_id': r.node_id, 'version': r.version, 'at': r.at.isoformat() if r.at else ''} for r in rows]


async def versions(program_id: str) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(VersionRow).where(VersionRow.program_id == program_id).order_by(VersionRow.version.desc()))).scalars()
        return [{'version': r.version, 'reason': r.reason, 'at': r.created_at.isoformat() if r.created_at else ''} for r in rows]


async def version_doc(program_id: str, version: int) -> ProgramDoc:
    async with sessionmaker()() as s:
        row = (await s.execute(select(VersionRow).where(VersionRow.program_id == program_id, VersionRow.version == version))).scalar_one_or_none()
        if row is None:
            raise NotFound('Версия не найдена')
        return ProgramDoc.model_validate(row.doc)


async def list_programs(owner: str | None = None) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        q = select(ProgramRow).order_by(ProgramRow.updated_at.desc()).limit(100)
        rows = (await s.execute(q)).scalars()
        return [{'id': r.id, 'title': r.title, 'status': r.status, 'version': r.version, 'updated_at': r.updated_at.isoformat() if r.updated_at else ''} for r in rows]


# --- Задания ---
async def create_job(program_id: str, kind: str) -> str:
    job_id = new_id('job')
    async with sessionmaker()() as s:
        s.add(JobRow(id=job_id, program_id=program_id, kind=kind, status='queued', progress={}))
        await s.commit()
    return job_id


async def update_job(job_id: str, *, status: str | None = None, progress: dict[str, Any] | None = None, error: str | None = None) -> None:
    async with sessionmaker()() as s:
        row = await s.get(JobRow, job_id)
        if row is None:
            return
        if status:
            row.status = status
        if progress is not None:
            row.progress = progress
        if error is not None:
            row.error = error[:2000]
        await s.commit()


async def get_job(job_id: str) -> dict[str, Any]:
    async with sessionmaker()() as s:
        row = await s.get(JobRow, job_id)
        if row is None:
            raise NotFound('Задание не найдено')
        return {'job_id': row.id, 'program_id': row.program_id, 'kind': row.kind, 'status': row.status, 'progress': row.progress or {}, 'error': row.error}


def run_job(job_id: str, coro_factory: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]) -> None:
    """Встроенная очередь asyncio: задание выполняется в фоне, прогресс пишется в БД."""

    async def _progress(p: dict[str, Any]) -> None:
        await update_job(job_id, progress=p)

    async def _runner() -> None:
        await update_job(job_id, status='running')
        try:
            await coro_factory(_progress)
            await update_job(job_id, status='done')
        except Exception as exc:  # noqa: BLE001 — статус failed, состояние программы сохранено
            logger.exception('Задание %s упало', job_id)
            msg = getattr(exc, 'message_ru', None) or f'{type(exc).__name__}'
            await update_job(job_id, status='failed', error=msg)

    task = asyncio.create_task(_runner())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
