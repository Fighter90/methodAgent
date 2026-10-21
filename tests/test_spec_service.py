"""Спецификация specs/programs-service.md: хранение программ, версии, журнал, уведомления, задания."""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core import db  # noqa: E402
from app.core.errors import NotFound, RateLimited  # noqa: E402
from app.programs import service as svc  # noqa: E402
from app.programs.schemas import Approval, Lecture, ProgramDoc, Status  # noqa: E402


@pytest.fixture
async def store(tmp_path, monkeypatch):
    """Отдельная SQLite-база на тест: сервис работает через подменённый sessionmaker."""
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "t.db"}')
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(svc, 'sessionmaker', lambda: maker)
    monkeypatch.setattr(svc, '_profile', lambda: {})
    yield maker
    await engine.dispose()


def _doc(pid: str = 'p-1', **kw) -> ProgramDoc:
    return ProgramDoc(id=pid, request='x', title=kw.pop('title', 'Программа'), **kw)


def test_new_id_format() -> None:
    """SPEC-SVC-01: new_id возвращает «префикс-10 hex-символов», идентификаторы не повторяются."""
    a, b = svc.new_id('job'), svc.new_id('job')
    assert a.startswith('job-') and len(a) == 14 and a != b


async def test_save_and_load_roundtrip(store) -> None:
    """SPEC-SVC-02: save сохраняет документ с владельцем и временем изменения; load возвращает тот же документ."""
    doc = _doc()
    doc.kit.lectures = [Lecture(id='l', topic_id='t', module_id='m', title='Л', duration_min=90, plan=[{'min': 10, 'text': 'a'}])]
    await svc.save(doc, owner='u-x')
    got = await svc.load('p-1')
    assert got.title == 'Программа' and got.updated_at
    assert sum(p['min'] for p in got.kit.lectures[0].plan) == 90  # хронометраж равен длительности
    assert await svc.owner_of('p-1') == 'u-x'
    doc.title = 'Новое'
    await svc.save(doc)
    assert (await svc.load('p-1')).title == 'Новое' and await svc.owner_of('p-1') == 'u-x'


async def test_missing_program_not_found(store) -> None:
    """SPEC-SVC-03: IF программы или версии нет, THEN load, owner_of и version_doc бросают NotFound."""
    with pytest.raises(NotFound):
        await svc.load('nope')
    with pytest.raises(NotFound):
        await svc.owner_of('nope')
    with pytest.raises(NotFound):
        await svc.version_doc('nope', 1)


async def test_snapshots_increment_version(store) -> None:
    """SPEC-SVC-04: save со snapshot увеличивает версию на 1 от максимума и сохраняет снимок с причиной; versions — от новой к старой."""
    doc = _doc()
    await svc.save(doc, reason='создание', snapshot=True)
    doc.title = 'v3'
    await svc.save(doc, reason='правка', snapshot=True)
    assert doc.version == 3
    vs = await svc.versions('p-1')
    assert [(v['version'], v['reason']) for v in vs] == [(3, 'правка'), (2, 'создание')]
    assert (await svc.version_doc('p-1', 2)).title == 'Программа'


async def test_events_with_before_after(store) -> None:
    """SPEC-SVC-05: журнал хранит кто, что, версию, «было/стало»; версия по умолчанию — текущая версия программы; имена актёров подставляются."""
    await svc.save(_doc(version=4))
    await svc.log_event('p-1', 'agent', 'edit', 'Правка темы', node_id='t1', before='старое', after='новое')
    await svc.log_event('p-1', 'u-madina', 'comment', 'Без было/стало', version=7)
    await svc.log_event('ghost', 'auto-approve', 'approve')
    ev = await svc.events('p-1')
    assert [e['action'] for e in ev] == ['comment', 'edit']
    assert ev[1] | {'at': ''} == {'actor': 'agent', 'actor_name': 'Агент', 'action': 'edit', 'text': 'Правка темы', 'before': 'старое',
                                  'after': 'новое', 'node_id': 't1', 'version': 4, 'at': ''}
    assert ev[0]['version'] == 7 and ev[0]['before'] == '' and ev[0]['actor_name'] != 'u-madina'
    ghost = await svc.events('ghost')
    assert ghost[0]['version'] == 1 and ghost[0]['actor_name'] == 'Агент (auto-approve)'


async def test_notifications_and_mark_read(store) -> None:
    """SPEC-SVC-06: уведомления сохраняются по пользователю (новые сверху), mark_read отмечает все или выбранные и возвращает число."""
    for i in range(3):
        await svc.notify('u-a', 'p-1', f'n{i}')
    await svc.notify('u-b', 'p-1', 'чужое')
    items = await svc.notifications('u-a')
    assert [n['text'] for n in items] == ['n2', 'n1', 'n0'] and not any(n['read'] for n in items)
    assert await svc.mark_read('u-a', [items[0]['id']]) == 1
    assert await svc.mark_read('u-a') == 2
    assert await svc.mark_read('u-a') == 0
    assert all(n['read'] for n in await svc.notifications('u-a'))
    assert not (await svc.notifications('u-b'))[0]['read']


async def test_notify_email_by_profile(store, monkeypatch) -> None:
    """SPEC-SVC-07: WHEN в профиле включены письма и у пользователя есть адрес, уведомление дублируется на почту (FR-59)."""
    sent = []
    monkeypatch.setattr(svc, '_profile', lambda: {'notify_email': True, 'experts': [{'id': 'u-e', 'email': 'e@x.ru'}]})
    monkeypatch.setattr(svc, '_send_mail', lambda to, text: sent.append((to, text)))
    await svc.notify('u-e', 'p', 'Модуль назначен')
    await svc.notify('u-none', 'p', 'Без адреса')
    assert sent == [('e@x.ru', 'Модуль назначен')]


def test_send_mail_smtp(monkeypatch) -> None:
    """SPEC-SVC-08: письмо уходит через SMTP профиля с STARTTLS и логином; без хоста не отправляется; ошибка SMTP не прерывает работу."""
    import smtplib

    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(('connect', host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            log.append('tls')

        def login(self, user, pwd):
            log.append(('login', user))

        def send_message(self, msg):
            log.append(('send', msg['To'], msg['From']))

    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setattr(svc, '_profile', lambda: {})
    svc._send_mail('a@x.ru', 't')
    assert log == []
    monkeypatch.setattr(svc, '_profile', lambda: {'smtp': {'host': 'smtp.x', 'port': 2525, 'user': 'bot@x.ru'}})
    svc._send_mail('a@x.ru', 't')
    assert log == [('connect', 'smtp.x', 2525), 'tls', ('login', 'bot@x.ru'), ('send', 'a@x.ru', 'bot@x.ru')]

    def broken(*a, **k):
        raise OSError('нет сети')

    monkeypatch.setattr(smtplib, 'SMTP', broken)
    svc._send_mail('a@x.ru', 't')


def test_head_ids_and_emails(monkeypatch) -> None:
    """SPEC-SVC-09: руководитель берётся из профиля организации, иначе — все пользователи с ролью head; адрес ищется среди экспертов, руководителя и методистов."""
    prof = {'head': {'id': 'u-h', 'email': 'h@x.ru'}, 'methodists': [{'id': 'u-m', 'email': 'm@x.ru'}]}
    monkeypatch.setattr(svc, '_profile', lambda: prof)
    assert svc.head_ids() == ['u-h']
    assert svc._email_of('u-m') == 'm@x.ru' and svc._email_of('u-h') == 'h@x.ru' and svc._email_of('x') == ''
    monkeypatch.setattr(svc, '_profile', lambda: {})
    from app.core.security import users

    assert svc.head_ids() == [u.id for u in users().values() if 'head' in u.roles]


async def test_list_programs_filters(store) -> None:
    """SPEC-SVC-10: list_programs фильтрует по владельцу и статусам; период считается по дате утверждения программы, а не сохранения (FR-50)."""
    a = _doc('p-a', status=Status.APPROVED)
    a.approvals = [Approval(stage='program', actor='u-h', decision='approve', at='2025-03-10T10:00:00')]
    await svc.save(a, owner='u-1')
    await svc.save(_doc('p-b'), owner='u-2')
    all_ = await svc.list_programs()
    assert {p['id'] for p in all_} == {'p-a', 'p-b'}
    assert [p['id'] for p in await svc.list_programs(owner='u-2')] == ['p-b']
    assert [p['id'] for p in await svc.list_programs(statuses={'approved'})] == ['p-a']
    got = await svc.list_programs(since='2025-03-01', until='2025-03-31')
    assert [p['id'] for p in got] == ['p-a'] and got[0]['decided_at'] == '2025-03-10T10:00:00'
    assert await svc.list_programs(since='2025-04-01', statuses={'approved'}) == []


async def test_jobs_lifecycle(store) -> None:
    """SPEC-SVC-11: задание создаётся в статусе queued, run_job переводит его в running → done и пишет прогресс."""
    job = await svc.create_job('p-1', 'kit')
    assert (await svc.get_job(job))['status'] == 'queued'
    assert {'job_id': job, 'program_id': 'p-1', 'kind': 'kit'} in await svc.unfinished_jobs()

    async def work(progress):
        await progress({'step': 'modules', 'done': 1})

    svc.run_job(job, work)
    await asyncio.gather(*list(svc._tasks))
    j = await svc.get_job(job)
    assert j['status'] == 'done' and j['progress'] == {'step': 'modules', 'done': 1}
    assert await svc.unfinished_jobs() == []


async def test_job_failure_recorded(store) -> None:
    """SPEC-SVC-12: IF задание упало, THEN статус failed и текст ошибки (message_ru или имя исключения, до 2000 символов)."""
    class Ru(Exception):
        message_ru = 'Модель недоступна'

    async def fail_ru(progress):
        raise Ru()

    async def fail_plain(progress):
        raise KeyError('x')

    j1, j2 = await svc.create_job('p', 'kit'), await svc.create_job('p', 'kit')
    svc.run_job(j1, fail_ru)
    svc.run_job(j2, fail_plain)
    await asyncio.gather(*list(svc._tasks))
    assert (await svc.get_job(j1))['error'] == 'Модель недоступна' and (await svc.get_job(j1))['status'] == 'failed'
    assert (await svc.get_job(j2))['error'] == 'KeyError'
    await svc.update_job(j2, error='е' * 5000)
    assert len((await svc.get_job(j2))['error']) == 2000
    await svc.update_job('job-missing', status='done')
    with pytest.raises(NotFound):
        await svc.get_job('job-missing')


def test_check_capacity(monkeypatch) -> None:
    """SPEC-SVC-13: IF запущено max_parallel_jobs заданий, THEN check_capacity бросает RateLimited (429)."""
    from app.core.config import get_settings

    limit = get_settings().max_parallel_jobs
    fake = {object() for _ in range(limit)}
    monkeypatch.setattr(svc, '_tasks', set(list(fake)[: limit - 1]))
    svc.check_capacity()
    monkeypatch.setattr(svc, '_tasks', fake)
    with pytest.raises(RateLimited):
        svc.check_capacity()


async def test_start_job_capacity_first_and_idempotent(store, monkeypatch) -> None:
    """SPEC-SVC-14, SPEC-SVC-15: ёмкость проверяется до создания задания (429 не оставляет записей),
    повторный вызов возвращает то же активное задание программы, cancel_job снимает резерв."""
    from app.core.config import get_settings

    limit = get_settings().max_parallel_jobs
    monkeypatch.setattr(svc, '_tasks', {object() for _ in range(limit)})
    with pytest.raises(RateLimited):
        await svc.start_job('p-1', 'kit')
    assert await svc.unfinished_jobs() == []  # 429 пришёл до изменения состояния: заданий нет

    monkeypatch.setattr(svc, '_tasks', set())
    j1, created = await svc.start_job('p-1', 'kit')
    assert created
    j2, created = await svc.start_job('p-1', 'kit')
    assert not created and j1 == j2  # один активный job на программу (идемпотентность)
    assert (await svc.get_job(j1))['status'] == 'queued'
    other, created = await svc.start_job('p-2', 'kit')
    assert created and other != j1  # другая программа — своё задание

    await svc.cancel_job(j1, 'утверждение не состоялось')
    assert (await svc.get_job(j1))['status'] == 'failed'
    j3, created = await svc.start_job('p-1', 'kit')
    assert created and j3 != j1  # резерв снят — задание можно создать снова
