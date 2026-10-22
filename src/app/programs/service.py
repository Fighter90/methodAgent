"""Сервис программ: загрузка и сохранение документа, версии, журнал, задания (job_id)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.core.db import (
    EventRow,
    JobRow,
    NotificationRow,
    ProgramRow,
    VersionRow,
    max_version,
    now_iso,
    sessionmaker,
)
from app.core.errors import NotFound, RateLimited
from app.programs.schemas import ProgramDoc, fit_plan

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
    for lec in doc.kit.lectures:
        # после любой правки часов хронометраж лекций равен их длительности (FR-28); план в
        # неожиданном формате (например, минуты строкой от модели) не валит сохранение (MET-5)
        try:
            lec.plan = fit_plan(lec.plan, lec.duration_min)
        except (TypeError, ValueError):
            logger.warning('program=%s lecture=%s: план в неожиданном формате — сохранён как есть', doc.id, lec.id)
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


_SEP = '\x1f'  # было/стало хранятся в тексте события: схема таблицы не меняется на развёрнутых стендах


async def log_event(
    program_id: str, actor: str, action: str, text: str = '', node_id: str = '', version: int | None = None,
    before: str = '', after: str = '',
) -> None:
    """Событие журнала (FR-58): кто, что, когда, версия комплекта, было и стало."""
    async with sessionmaker()() as s:
        if version is None:
            row = await s.get(ProgramRow, program_id)
            version = row.version if row else 1
        clean = lambda x: str(x or '').replace(_SEP, ' ')  # текст события не должен содержать разделитель
        body = clean(text)[:2000] + (f'{_SEP}{clean(before)[:1000]}{_SEP}{clean(after)[:1000]}' if before or after else '')
        s.add(EventRow(program_id=program_id, actor=actor, action=action, text=body, node_id=node_id, version=version))
        await s.commit()


async def owner_of(program_id: str) -> str:
    async with sessionmaker()() as s:
        row = await s.get(ProgramRow, program_id)
        if row is None:
            raise NotFound('Программа не найдена')
        return row.owner


def _profile() -> dict[str, Any]:
    from app.kb.registry import org_profile

    return org_profile()


def head_ids() -> list[str]:
    from app.core.security import users

    own = (_profile().get('head') or {}).get('id')
    return [own] if own else [u.id for u in users().values() if 'head' in u.roles]


def _email_of(user_id: str) -> str:
    prof = _profile()
    for person in [*(prof.get('experts') or []), prof.get('head') or {}, *(prof.get('methodists') or [])]:
        if person.get('id') == user_id:
            return person.get('email', '')
    return ''


def _send_mail(to: str, text: str) -> None:
    """Почта по настройке профиля (FR-59): SMTP из профиля, пароль — из настроек администратора (зашифрован) или SMTP_PASSWORD."""
    import os
    import smtplib
    from email.message import EmailMessage

    from app.core.config import get_settings

    smtp = _profile().get('smtp') or {}
    if not smtp.get('host'):
        return
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = 'МетодАгент: уведомление', smtp.get('from') or smtp.get('user', ''), to
    msg.set_content(text)
    try:
        with smtplib.SMTP(smtp['host'], int(smtp.get('port', 587)), timeout=10) as srv:
            srv.starttls()
            if smtp.get('user'):
                srv.login(smtp['user'], get_settings().smtp_password or os.environ.get('SMTP_PASSWORD', ''))
            srv.send_message(msg)
    except (OSError, smtplib.SMTPException):
        logger.warning('уведомление по почте не отправлено')


async def notify(user_id: str, program_id: str, text: str) -> None:
    """Уведомление в интерфейсе; по почте — если включено в профиле и у пользователя есть адрес."""
    async with sessionmaker()() as s:
        s.add(NotificationRow(user_id=user_id, program_id=program_id, text=text))
        await s.commit()
    if _profile().get('notify_email') and (to := _email_of(user_id)):
        await asyncio.to_thread(_send_mail, to, text)


async def notifications(user_id: str) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(NotificationRow).where(NotificationRow.user_id == user_id).order_by(NotificationRow.id.desc()).limit(30))).scalars()
        return [{'id': r.id, 'program_id': r.program_id, 'text': r.text, 'read': bool(r.read), 'at': r.at.isoformat() if r.at else ''} for r in rows]


async def mark_read(user_id: str, ids: list[int] | None = None) -> int:
    async with sessionmaker()() as s:
        q = select(NotificationRow).where(NotificationRow.user_id == user_id, NotificationRow.read == 0)
        if ids:
            q = q.where(NotificationRow.id.in_(ids))
        rows = list((await s.execute(q)).scalars())
        for r in rows:
            r.read = 1
        await s.commit()
        return len(rows)


async def events(program_id: str) -> list[dict[str, Any]]:
    async with sessionmaker()() as s:
        rows = (await s.execute(select(EventRow).where(EventRow.program_id == program_id).order_by(EventRow.id.desc()).limit(200))).scalars()
        from app.core.security import users

        names = {k: u.name for k, u in users().items()} | {'agent': 'Агент', 'auto-approve': 'Агент (auto-approve)'}
        out = []
        for r in rows:
            text, before, after = ((r.text or '').split(_SEP) + ['', ''])[:3]
            out.append({'actor': r.actor, 'actor_name': names.get(r.actor, r.actor), 'action': r.action, 'text': text, 'before': before, 'after': after, 'node_id': r.node_id, 'version': r.version, 'at': r.at.isoformat() if r.at else ''})
        return out


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


async def list_programs(owner: str | None = None, statuses: set[str] | None = None, since: str = '', until: str = '') -> list[dict[str, Any]]:
    """Список программ; руководитель фильтрует «на утверждении» и утверждённые за период (FR-50)."""
    async with sessionmaker()() as s:
        q = select(ProgramRow).order_by(ProgramRow.updated_at.desc()).limit(200)
        if statuses:
            q = q.where(ProgramRow.status.in_(statuses))
        if owner:
            q = q.where(ProgramRow.owner == owner)
        rows = (await s.execute(q)).scalars()
        out = []
        for r in rows:
            at = r.updated_at.isoformat() if r.updated_at else ''
            doc = r.doc or {}
            # Период руководителя считается по дате утверждения (или отправки), а не последнего сохранения
            decided = [a.get('at', '') for a in doc.get('approvals') or [] if a.get('stage') == 'program']
            when = (decided[-1] if decided else at)[:10]
            if (since and when < since) or (until and when > until):
                continue
            out.append({
                'id': r.id, 'title': r.title, 'status': r.status, 'version': r.version, 'updated_at': at, 'owner': r.owner,
                'type': doc.get('type'), 'template': doc.get('template', ''), 'volume_h': doc.get('volume_h', 0),
                'blocking': (doc.get('report') or {}).get('blocking_passed'), 'cost_rub': round((doc.get('usage') or {}).get('cost_rub', 0.0), 2),
                'decided_at': decided[-1] if decided else '',
            })
        return out


# --- Задания ---
async def create_job(program_id: str, kind: str) -> str:
    job_id = new_id('job')
    async with sessionmaker()() as s:
        s.add(JobRow(id=job_id, program_id=program_id, kind=kind, status='queued', progress={}))
        await s.commit()
    return job_id


async def start_job(program_id: str, kind: str) -> tuple[str, bool]:
    """Ёмкость и задание резервируются до изменения состояния документа (аудит 19.10, F05).

    Сначала проверяется лимит параллельных заданий: 429 приходит до того, что-либо изменилось.
    IF у программы уже есть активное задание (queued или running), THEN возвращается оно
    (created=False) — на программе выполняется не больше одного активного задания, а повторный
    вызов идемпотентен.
    """
    check_capacity()
    async with sessionmaker()() as s:
        row = (await s.execute(
            select(JobRow)
            .where(JobRow.program_id == program_id, JobRow.status.in_(('queued', 'running')))
            .order_by(JobRow.id.desc())
            .limit(1)
        )).scalars().first()
        if row is not None:
            return row.id, False
        job_id = new_id('job')
        s.add(JobRow(id=job_id, program_id=program_id, kind=kind, status='queued', progress={}))
        await s.commit()
        return job_id, True


async def cancel_job(job_id: str, error: str = 'Действие не выполнено: резерв задания снят') -> None:
    """Снимает резерв задания, если действие прервалось до его запуска: задание закрывается как failed."""
    await update_job(job_id, status='failed', error=error)


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


async def unfinished_jobs() -> list[dict[str, Any]]:
    """Задания, прерванные перезапуском контейнера (NFR-08): их перезапускает lifespan."""
    async with sessionmaker()() as s:
        rows = (await s.execute(select(JobRow).where(JobRow.status.in_(('queued', 'running'))))).scalars()
        return [{'job_id': r.id, 'program_id': r.program_id, 'kind': r.kind} for r in rows]


def check_capacity() -> None:
    """429 при превышении лимита параллельных заданий (ТЗ, таблица 20)."""
    from app.core.config import get_settings

    limit = get_settings().max_parallel_jobs
    if len(_tasks) >= limit:
        raise RateLimited(f'Сейчас выполняется {len(_tasks)} заданий — это предел стенда. Повторите через минуту.')


def run_job(job_id: str, coro_factory: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]) -> None:
    """Встроенная очередь asyncio: задание выполняется в фоне, прогресс пишется в БД."""

    async def _progress(p: dict[str, Any]) -> None:
        await update_job(job_id, progress=p)

    async def _runner() -> None:
        await update_job(job_id, status='running')
        try:
            await coro_factory(_progress)
            await update_job(job_id, status='done')
        except Exception as exc:  # noqa: BLE001 — страховка очереди: любая ошибка задания → status failed с текстом, а не потерянная задача
            logger.exception('Задание %s упало', job_id)
            msg = getattr(exc, 'message_ru', None) or f'{type(exc).__name__}'
            await update_job(job_id, status='failed', error=msg)

    task = asyncio.create_task(_runner())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
