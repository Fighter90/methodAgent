"""Методы API /api/v1 (ТЗ, таблица 19) и контракт автопрогона POST /programs?mode=auto."""

from __future__ import annotations

import base64
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.agent import workflow as wf
from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import BadRequest, Conflict, ForbiddenRole, Unauthorized
from app.core.security import Principal, current_principal, require, users
from app.export import service as export
from app.kb.files import parse_reference
from app.programs import service as svc
from app.programs.schemas import Assumption, ProgramDoc, ReferenceInfo, Status

router = APIRouter(prefix='/programs', tags=['programs'])
misc = APIRouter(tags=['misc'])


async def _load_for(program_id: str, p: Principal) -> ProgramDoc:
    """Загрузка с проверкой прав: API-клиент видит только свои программы и задания (ТЗ, 4.1), администратор программ не видит."""
    if p.role == 'admin':
        raise ForbiddenRole('Администратор ведёт пользователей и настройки; программы ведут методист, эксперт и руководитель')
    doc = await svc.load(program_id)
    if p.role == 'api' and await svc.owner_of(program_id) != p.user_id:
        if p.anonymous:
            raise Unauthorized('Нужен вход: заголовок Authorization: Bearer <токен> (POST /api/v1/auth/login)')
        raise ForbiddenRole('API-клиент видит только свои программы и задания')
    return doc


def expert_modules(doc: ProgramDoc, p: Principal) -> set[str]:
    return {m.id for m in doc.modules if m.expert_id == p.user_id}


def expert_view(doc: ProgramDoc, p: Principal, data: dict[str, Any]) -> dict[str, Any]:
    """FR-44: эксперт видит только назначенные модули и их элементы комплекта."""
    mine = expert_modules(doc, p)
    data['modules'] = [m for m in data['modules'] if m['id'] in mine]
    kit = data.get('kit') or {}
    for key in ('module_programs', 'questions', 'tasks', 'lectures', 'assessments'):
        kit[key] = [x for x in kit.get(key) or [] if x.get('module_id') in mine]
    data['comments'] = [c for c in data.get('comments') or [] if c.get('module_id') in mine]
    return data


class Attachment(BaseModel):
    name: str
    content_base64: str


class CreateProgram(BaseModel):
    request: str = Field(min_length=5, max_length=5000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)
    norm_mode: Literal['gos', 'org'] = 'gos'
    wait: bool = True
    # Ответы методиста на вопросы, если автопрогон их знает заранее (ключ — поле или id вопроса)
    answers: dict[str, str] = Field(default_factory=dict)


def _parse_files(files: list[tuple[str, bytes]]) -> tuple[list[ReferenceInfo], str]:
    s = get_settings()
    if len(files) > s.max_files_per_request:
        raise BadRequest(f'Не больше {s.max_files_per_request} файлов на запрос')
    refs, texts = [], []
    for name, content in files:
        if len(content) > s.max_file_size_bytes:
            raise BadRequest(f'Файл «{name}» больше {s.max_file_size_mb} МБ')
        parsed = parse_reference(name, content)
        refs.append(ReferenceInfo(name=name, chars=len(parsed.text), structure=parsed.structure, hours_issues=parsed.hours_issues, text_sample=parsed.text[:120000]))
        texts.append(parsed.text[:3000])
    return refs, '\n'.join(texts)


def _auto_response(doc: ProgramDoc, base: str) -> dict[str, Any]:
    """Поля ответа автопрогона (ТЗ, таблица 21)."""
    rep = doc.report
    failed = [r.id for r in rep.rules if r.status == 'fail'] if rep else []
    status = 'done' if doc.status == Status.KIT_READY and not failed else ('done_with_errors' if doc.kit.questions else 'failed')
    tot = doc.totals()
    return {
        'program_id': doc.id,
        'status': status,
        'assumptions': [a.model_dump() for a in doc.assumptions],
        'questions_skipped': [q.model_dump() for q in doc.questions],
        'skeleton': {
            'template': doc.template,
            'type': doc.type.value if doc.type else None,
            'issued_document': doc.issued_document,
            'title': doc.title,
            'goal': doc.goal,
            'ps_code': doc.profstandard.code if doc.profstandard else None,
            'volume_h': doc.volume_h,
            'competencies': [c.model_dump() for c in doc.competencies],
            'modules': [
                {'n': m.n, 'title': m.title, **m.hours.model_dump(), 'control': m.control,
                 'topics': [{'n': t.n, 'title': t.title, **t.hours.model_dump(), 'lo_ids': t.lo_ids} for t in m.topics]}
                for m in doc.modules
            ],
            'final_assessment': doc.final_assessment.model_dump(),
            'totals': {'lk': tot.lk, 'pr': tot.pr, 'lb': tot.lb, 'srs': tot.srs, 'ia': doc.final_assessment.hours, 'all': tot.total + doc.final_assessment.hours},
            'calendar': doc.calendar.model_dump(),
        },
        'kit': export.kit_json(doc),
        'report': {
            'rules_passed': sum(1 for r in rep.rules if r.status != 'fail') if rep else 0,
            'rules_total': len(rep.rules) if rep else 0,
            'blocking_checks': f'{rep.blocking_passed}/{rep.blocking_total}' if rep else '0/10',
            'failed_rules': failed,
            'unconfirmed_sources': sum(1 for s in doc.sources if not s.confirmed),
            'rules': [r.model_dump() for r in rep.rules] if rep else [],
            'coverage': rep.coverage if rep else [],
        },
        'agent_notes': doc.agent_notes,
        'files': {fmt: f'{base}/api/v1/programs/{doc.id}/export/{fmt}' for fmt in export.FORMATS},
        'timing_s': doc.timing_s,
        'tokens': {'in': doc.usage.tokens_in, 'out': doc.usage.tokens_out, 'cost_rub': round(doc.usage.cost_rub, 2), 'calls': doc.usage.calls},
    }


async def _new_doc(text: str, files: list[tuple[str, bytes]], mode: str, norm_mode: str, owner: str) -> ProgramDoc:
    refs, ref_text = _parse_files(files)
    doc = ProgramDoc(id=svc.new_id('prg'), request=text.strip(), mode=mode, norm_mode=norm_mode, created_at=now_iso())
    await wf.intake_step(doc, refs, ref_text)
    await svc.log_event(doc.id, owner, 'created', f'Запрос: {text[:200]}')
    return doc


async def _auto_pipeline(doc: ProgramDoc, owner: str) -> ProgramDoc:
    wf.fill_defaults(doc)
    await wf.skeleton_step(doc)
    if doc.calendar.conflict and not doc.calendar.chosen_option:
        wf.choose_calendar_option(doc, 'six_days' if doc.params.max_hours_per_day else 'extend')
        doc.assumptions.append(Assumption(field='calendar', value=doc.calendar.chosen_option, source='auto: ограничение нагрузки в день сохранено'))
    # auto-approve только без ✕: сначала до двух попыток repair, затем комплект со статусом done_with_errors (контракт автопрогона)
    for attempt in range(3):
        try:
            wf.approve_skeleton(doc, 'auto-approve', auto=True)
            break
        except Conflict:
            if attempt < 2 and doc.report:
                from app.validation.repair import repair

                fixed = repair(doc, doc.report.rules)
                wf.recompute(doc)
                if fixed:
                    continue
            doc.agent_notes.append('Каркас содержит ошибки ✕ и после repair — в режиме auto комплект собран со статусом done_with_errors')
            doc.status = Status.SKELETON_APPROVED
            break
    await svc.save(doc, owner, reason='каркас', snapshot=True)
    await wf.generate_kit(doc)
    await svc.save(doc, owner, reason='комплект', snapshot=True)
    await svc.log_event(doc.id, 'agent', 'kit_ready', f'Блокирующие проверки {doc.report.blocking_passed}/10' if doc.report else '')
    return doc


@router.post('', status_code=200, summary='Создать программу из запроса (JSON); mode=auto — полный комплект без вопросов')
async def create_program(
    body: CreateProgram,
    request: Request,
    mode: Literal['interactive', 'auto'] = Query('interactive'),
    p: Principal = Depends(require('methodist', 'api')),
) -> dict[str, Any]:
    files = []
    for a in body.attachments:
        try:
            files.append((a.name, base64.b64decode(a.content_base64)))
        except ValueError as exc:
            raise BadRequest(f'Файл «{a.name}»: неверный base64') from exc
    started = time.monotonic()
    doc = await _new_doc(body.request, files, mode, body.norm_mode, p.user_id)
    base = str(request.base_url).rstrip('/')
    if mode == 'auto':
        if doc.questions and body.answers:
            doc.status = Status.QUESTIONS
            wf.answer_questions(doc, body.answers)
        doc.status = Status.SKELETON
        if not body.wait:
            svc.check_capacity()
            await svc.save(doc, p.user_id)
            job_id = await svc.create_job(doc.id, 'auto')

            svc.run_job(job_id, _auto_job(doc.id, p.user_id))
            return JSONResponse({'program_id': doc.id, 'job_id': job_id, 'status': 'queued'}, status_code=202)  # type: ignore[return-value]
        try:
            doc = await _auto_pipeline(doc, p.user_id)
        except Exception as exc:  # noqa: BLE001 — автопрогон получает status: failed, а не 500 (таблица 21)
            doc.status = Status.FAILED
            doc.agent_notes.append(f'Сборка прервана: {getattr(exc, "message_ru", None) or type(exc).__name__}')
            await svc.save(doc, p.user_id)
            return {**_auto_response(doc, base), 'status': 'failed'}
        doc.timing_s['total'] = round(time.monotonic() - started, 2)
        await svc.save(doc, p.user_id)
        return _auto_response(doc, base)
    if doc.questions:
        doc.status = Status.QUESTIONS
        await svc.save(doc, p.user_id)
        return {'program_id': doc.id, 'status': doc.status.value, 'questions': [q.model_dump() for q in doc.questions], 'program': doc.model_dump(mode='json')}
    await wf.skeleton_step(doc)
    await svc.save(doc, p.user_id, reason='каркас', snapshot=True)
    return {'program_id': doc.id, 'status': doc.status.value, 'program': doc.model_dump(mode='json')}


@router.post('/upload', summary='Создать программу: текст и файлы multipart/form-data (интерфейс)')
async def create_program_upload(
    request: Request,
    text: str = Form(..., min_length=5, max_length=5000),
    norm_mode: str = Form('gos'),
    files: list[UploadFile] = File(default_factory=list),
    p: Principal = Depends(require('methodist', 'api')),
) -> dict[str, Any]:
    raw = [(f.filename or 'file', await f.read()) for f in files if f.filename]
    doc = await _new_doc(text, raw, 'interactive', norm_mode if norm_mode in ('gos', 'org') else 'gos', p.user_id)
    if doc.questions:
        doc.status = Status.QUESTIONS
        await svc.save(doc, p.user_id)
    else:
        doc.status = Status.SKELETON
        await svc.save(doc, p.user_id)
        job_id = await svc.create_job(doc.id, 'skeleton')
        svc.run_job(job_id, _skeleton_job(doc.id, p.user_id))
        return {'program_id': doc.id, 'status': 'skeleton_building', 'job_id': job_id, 'program': doc.model_dump(mode='json')}
    return {'program_id': doc.id, 'status': doc.status.value, 'program': doc.model_dump(mode='json')}


def _kit_job(program_id: str, owner: str):
    async def _job(progress):
        d = await svc.load(program_id)
        await wf.generate_kit(d, progress)
        await svc.save(d, owner, reason='комплект', snapshot=True)
        await svc.log_event(program_id, 'agent', 'kit_ready', f'Блокирующие проверки {d.report.blocking_passed}/10' if d.report else '', version=d.version)

    return _job


def _auto_job(program_id: str, owner: str):
    async def _job(progress):
        d = await svc.load(program_id)
        if d.status in (Status.SKELETON_APPROVED, Status.GENERATING):
            # перезапуск после рестарта: каркас уже сохранён, собирается только комплект
            await wf.generate_kit(d, progress)
            await svc.save(d, owner, reason='комплект', snapshot=True)
        else:
            await _auto_pipeline(d, owner)

    return _job


async def resume_jobs() -> int:
    """NFR-08: задания, прерванные перезапуском, продолжаются с последнего сохранённого шага."""
    n = 0
    for j in await svc.unfinished_jobs():
        try:
            owner = await svc.owner_of(j['program_id'])
        except Exception:  # noqa: BLE001 — программа удалена: задание закрывается
            await svc.update_job(j['job_id'], status='failed', error='Программа не найдена после перезапуска')
            continue
        factory = {'skeleton': lambda: _skeleton_job(j['program_id'], owner), 'kit': lambda: _kit_job(j['program_id'], owner),
                   'auto': lambda: _auto_job(j['program_id'], owner)}.get(j['kind'])
        if factory is None:
            await svc.update_job(j['job_id'], status='failed', error='Прервано перезапуском — повторите действие')
            continue
        svc.run_job(j['job_id'], factory())
        n += 1
    return n


def _skeleton_job(program_id: str, owner: str, comment: str = ''):
    async def _job(progress):
        await progress({'step': 'skeleton', 'text': 'Собираю каркас: компетенции, модули, темы, часы'})
        d = await svc.load(program_id)
        await wf.skeleton_step(d, comment)
        await svc.save(d, owner, reason='каркас', snapshot=True)
        await svc.log_event(program_id, 'agent', 'skeleton_built', f'Каркас за {d.timing_s.get("skeleton", 0)} с', version=d.version)

    return _job


@router.get('', summary='Список программ; status=on_approval,approved и since/until (ГГГГ-ММ-ДД) — фильтр руководителя')
async def list_programs(
    status: str = Query('', description='Статусы через запятую'),
    since: str = Query('', pattern=r'^(\d{4}-\d{2}-\d{2})?$'),
    until: str = Query('', pattern=r'^(\d{4}-\d{2}-\d{2})?$'),
    p: Principal = Depends(current_principal),
) -> list[dict[str, Any]]:
    if p.role == 'admin':
        raise ForbiddenRole('Администратор ведёт пользователей и настройки; программы ведут методист, эксперт и руководитель')
    statuses = {x.strip() for x in status.split(',') if x.strip()} or None
    items = await svc.list_programs(owner=p.user_id if p.role == 'api' else None, statuses=statuses, since=since, until=until)
    if p.role == 'expert':
        mine = {r['program_id'] for r in await _reviews_of(p.user_id)}
        items = [x for x in items if x['id'] in mine]
    return items


@router.get('/{program_id}', summary='Состояние программы: вопросы, каркас или комплект в JSON')
async def get_program(program_id: str, p: Principal = Depends(current_principal)) -> dict[str, Any]:
    if p.role == 'admin':
        raise ForbiddenRole('Администратор ведёт пользователей и настройки; программы ведут методист, эксперт и руководитель')
    doc = await _load_for(program_id, p)
    data = doc.model_dump(mode='json')
    if p.role == 'expert':
        if not expert_modules(doc, p):
            raise ForbiddenRole('Эксперт видит только программы с назначенными ему модулями')
        data = expert_view(doc, p, data)
    for a in data.get('approvals') or []:
        a['actor_name'] = users()[a['actor']].name if a.get('actor') in users() else a.get('actor')
    data['readiness'] = wf.readiness(doc)
    if p.role in ('head', 'methodist'):
        data['quality'] = wf.quality(doc, await svc.events(program_id))
    data['totals'] = doc.totals().model_dump()
    # Комплект по схеме 4.8 (таблица 19); остальные поля — состояние для интерфейса
    data['program'] = export.kit_json(doc)['program'] if p.role != 'expert' else None
    return data


class Answers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


@router.post('/{program_id}/answers', status_code=202, summary='Ответы на уточняющие вопросы; запускает сборку каркаса')
async def answers(program_id: str, body: Answers, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.answer_questions(doc, body.answers)
    doc.status = Status.SKELETON
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'answers', '; '.join(f'{q.text} — {q.answer}' for q in doc.questions))
    job_id = await svc.create_job(program_id, 'skeleton')
    svc.run_job(job_id, _skeleton_job(program_id, p.user_id))
    return {'job_id': job_id, 'status': 'queued'}


@router.patch('/{program_id}/skeleton', summary='Изменить часы, названия, формулировки; пересчёт и проверки')
async def patch_skeleton(program_id: str, body: dict[str, Any], p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.patch_skeleton(doc, body)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'skeleton_patch', _patch_summary(doc, body))
    return {'program': doc.model_dump(mode='json'), 'totals': doc.totals().model_dump()}


_KIND_RU = {'lk': 'ЛК', 'pr': 'ПР', 'lb': 'ЛБ', 'srs': 'СРС'}


def _patch_summary(doc: ProgramDoc, body: dict[str, Any]) -> str:
    """Правка каркаса словами для журнала (FR-58): что поменяли, без внутреннего JSON."""
    parts: list[str] = []
    for mp in body.get('modules', []):
        m = doc.module_by_id(mp.get('id', ''))
        name = f'модуль {m.n}' if m else 'модуль'
        if 'title' in mp:
            parts.append(f'{name}: название «{mp["title"]}»')
        if mp.get('hours'):
            parts.append(f'{name}: ' + ', '.join(f'{_KIND_RU.get(k, k)} {v} ч' for k, v in mp['hours'].items()))
        for tp in mp.get('topics', []):
            t = next((x for x in doc.all_topics() if x.id == tp.get('id')), None)
            tn = f'тема {t.n}' if t else 'тема'
            if 'title' in tp:
                parts.append(f'{tn}: название «{tp["title"]}»')
            if tp.get('hours'):
                parts.append(f'{tn}: ' + ', '.join(f'{_KIND_RU.get(k, k)} {v} ч' for k, v in tp['hours'].items()))
    if body.get('competencies'):
        parts.append(f'формулировки компетенций: {len(body["competencies"])}')
    if body.get('outcomes'):
        parts.append(f'формулировки РО: {len(body["outcomes"])}')
    if 'goal' in body:
        parts.append('цель программы')
    if 'final_hours' in body:
        parts.append(f'итоговая аттестация {body["final_hours"]} ч')
    if 'calendar_option' in body:
        parts.append(f'вариант графика {body["calendar_option"]}')
    return 'Каркас: ' + ('; '.join(parts) or 'без изменений')


class DecisionIn(BaseModel):
    rule_id: str
    decision: Literal['accept', 'keep']
    node: str = ''
    proposal: str = ''
    option_id: str = ''


@router.post('/{program_id}/skeleton/decisions', summary='Решение методиста по пункту «!»')
async def skeleton_decision(program_id: str, body: DecisionIn, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.decide(doc, body.rule_id, body.decision, p.user_id, body.node, body.proposal, body.option_id)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'decision', f'{body.rule_id}: {"принято" if body.decision == "accept" else "оставлено"} {body.proposal}')
    return {'program': doc.model_dump(mode='json')}


class ApproveIn(BaseModel):
    decision: Literal['approve', 'return'] = 'approve'
    comment: str = ''


@router.post('/{program_id}/skeleton/approve', status_code=202, summary='Утвердить каркас (запускает генерацию) или вернуть с комментарием')
async def approve(program_id: str, body: ApproveIn, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    if body.decision == 'return':
        wf.return_skeleton(doc, p.user_id, body.comment)
        await svc.save(doc, p.user_id)
        job_id = await svc.create_job(program_id, 'skeleton')
        svc.run_job(job_id, _skeleton_job(program_id, p.user_id, body.comment))
        await svc.log_event(program_id, p.user_id, 'skeleton_returned', body.comment)
        return {'job_id': job_id, 'status': 'queued'}
    wf.approve_skeleton(doc, p.user_id)
    await svc.save(doc, p.user_id, reason='каркас утверждён', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'skeleton_approved', 'Каркас утверждён методистом', version=doc.version)
    svc.check_capacity()
    job_id = await svc.create_job(program_id, 'kit')
    svc.run_job(job_id, _kit_job(program_id, p.user_id))
    return {'job_id': job_id, 'status': 'queued'}


@router.get('/{program_id}/report', summary='Отчёт автопроверки и матрица покрытия')
async def report(program_id: str, p: Principal = Depends(require('methodist', 'head', 'api'))) -> dict[str, Any]:
    doc = await _load_for(program_id, p)
    return doc.report.model_dump() if doc.report else {}


class EditIn(BaseModel):
    target: str = Field('', description='id темы, вопроса, задания, теста, лекции или слайда; hours:<id темы> — часы; пусто — агент найдёт элемент по тексту')
    instruction: str = ''
    new_title: str = ''
    hours: dict[str, int] | None = Field(None, description='для hours:<id темы>: {"lk": 2, "pr": 4, ...}')
    dry_run: bool = False


@router.post('/{program_id}/edits', summary='Точечная правка; dry_run=true — только список затрагиваемых элементов и «было / станет»')
async def edits(program_id: str, body: EditIn, p: Principal = Depends(require('methodist', 'expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    target = wf.resolve_target(doc, body.target, body.instruction)
    if p.role == 'expert':
        # FR-48: эксперт правит только свои модули и не меняет часы и РО
        if target.startswith('hours:'):
            raise ForbiddenRole('Эксперт не меняет часы — это решение методиста')
        lec = wf._lecture_of(doc, target)
        owner_module = next((m.id for m in doc.modules if any(t.id == target for t in m.topics)), None)
        owner_module = owner_module or next((x.module_id for x in [*doc.kit.questions, *doc.kit.tasks] if x.id == target), None)
        owner_module = owner_module or (lec.module_id if lec else None)
        if owner_module not in expert_modules(doc, p):
            raise ForbiddenRole('Эксперт правит только свои модули')
    try:
        result = await wf.edit(doc, target, body.instruction, body.new_title, body.dry_run, body.hours)
    except Conflict:
        if not body.dry_run:
            await svc.log_event(program_id, p.user_id, 'edit_rejected', f'{target}: {body.instruction}', node_id=target)
        raise
    if not body.dry_run:
        await svc.save(doc, p.user_id, reason=f'правка {target}', snapshot=True)
        prev = result.get('preview') or {}
        await svc.log_event(program_id, p.user_id, 'edit', f'{target}: {body.instruction}', node_id=target, version=doc.version,
                            before=prev.get('before', ''), after=prev.get('after', ''))
    return {**result, 'program': doc.model_dump(mode='json')}


@router.get('/{program_id}/versions', summary='Версии комплекта')
async def versions(program_id: str, p: Principal = Depends(require('methodist', 'head'))) -> list[dict[str, Any]]:
    return await svc.versions(program_id)


@router.post('/{program_id}/versions/{version}/restore', summary='Откат к версии')
async def restore(program_id: str, version: int, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    cur = await svc.load(program_id)
    doc = await svc.version_doc(program_id, version)
    wf.restore_into(doc, cur)
    await svc.save(doc, p.user_id, reason=f'откат к версии {version}', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'restore', f'Откат к версии {version}', version=doc.version, before=f'v{cur.version} · {cur.status.value}', after=f'v{doc.version} · {doc.status.value}')
    return {'version': doc.version, 'status': doc.status.value}


class ExpertIn(BaseModel):
    expert_id: str


@router.put('/{program_id}/modules/{module_id}/expert', summary='Назначить эксперта на модуль')
async def assign_expert(program_id: str, module_id: str, body: ExpertIn, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    if body.expert_id not in users() or 'expert' not in users()[body.expert_id].roles:
        raise BadRequest('Такого эксперта нет в профиле организации')
    doc = await svc.load(program_id)
    wf.assign_expert(doc, module_id, body.expert_id)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'assign', f'Модуль {module_id} → {users()[body.expert_id].name}', node_id=module_id)
    await svc.notify(body.expert_id, program_id, f'Вам назначен модуль «{doc.module_by_id(module_id).title}» программы «{doc.title}»')
    return {'program': doc.model_dump(mode='json')}


class CommentIn(BaseModel):
    module_id: str
    text: str = Field(min_length=1, max_length=2000)
    node_id: str = ''
    ask_agent: bool = False


@router.post('/{program_id}/comments', summary='Комментарий к фрагменту; ask_agent=true — запрос правки агенту')
async def comment(program_id: str, body: CommentIn, p: Principal = Depends(require('expert', 'methodist'))) -> dict[str, Any]:
    from app.skills.review_assist.run import propose_full

    doc = await svc.load(program_id)
    if p.role == 'expert' and body.module_id not in expert_modules(doc, p):
        raise ForbiddenRole('Эксперт комментирует только свои модули')
    prop = await propose_full(doc, body.module_id, body.node_id, body.text) if body.ask_agent else None
    c = wf.add_comment(doc, body.module_id, p.user_id, body.text, body.node_id, prop.proposal if prop else '', prop.affected if prop else None)
    if prop and p.role == 'expert':
        c.status = 'proposed'  # эксперт сам попросил агента: правка ждёт его подтверждения (FR-48)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'comment', body.text, node_id=body.node_id)
    await svc.notify(await svc.owner_of(program_id), program_id, f'{p.name}: {body.text[:120]}')
    return {'comment': c.model_dump()}


class AnswerIn(BaseModel):
    comment_id: str
    answer: str = ''
    apply_proposal: bool = False
    ask_agent: bool = False


@router.post('/{program_id}/comments/answer', summary='Ответ методиста, «Передать агенту» или применение правки (после подтверждения эксперта)')
async def answer_comment(program_id: str, body: AnswerIn, p: Principal = Depends(require('methodist', 'expert'))) -> dict[str, Any]:
    from app.skills.review_assist.run import propose_full

    doc = await svc.load(program_id)
    c = next((x for x in doc.comments if x.id == body.comment_id), None)
    if c is None:
        raise BadRequest('Комментарий не найден')
    if p.role == 'expert' and c.module_id not in expert_modules(doc, p):
        raise ForbiddenRole('Эксперт работает только со своими модулями')
    applied = False
    if body.ask_agent:
        # FR-41: методист передаёт вопрос агенту — предложение и затрагиваемые элементы
        prop = await propose_full(doc, c.module_id, c.node_id, c.text)
        c.agent_proposal, c.affected = prop.proposal, prop.affected
        author_role = users()[c.author].roles[0] if c.author in users() else ''
        c.status = 'proposed' if author_role == 'expert' else 'open'
        if author_role == 'expert':
            await svc.notify(c.author, program_id, f'Агент предложил правку по вашему замечанию — подтвердите в модуле: {prop.proposal[:120]}')
    elif body.apply_proposal and c.node_id:
        author_is_expert = c.author in users() and 'expert' in users()[c.author].roles
        if author_is_expert and p.role != 'expert':
            c.status = 'proposed'  # FR-48: правку по замечанию эксперта подтверждает сам эксперт
            await svc.notify(c.author, program_id, 'Методист передал правку агента — подтвердите её в модуле')
        else:
            await wf.edit(doc, c.node_id.partition('#')[0], c.agent_proposal or c.text)
            c.status, applied = 'applied', True
    else:
        c.answer, c.status = body.answer, 'answered'
    m = doc.module_by_id(c.module_id)
    if m and m.review_status == 'question' and c.status in ('answered', 'applied'):
        m.review_status = 'in_review'
    await svc.save(doc, p.user_id, reason='правка по замечанию эксперта' if applied else '', snapshot=applied)
    await svc.log_event(program_id, p.user_id, 'comment_answer', body.answer or ('Правка агента применена' if applied else 'Предложение агента'), node_id=c.node_id)
    if c.author and c.author != p.user_id and c.status == 'answered':
        await svc.notify(c.author, program_id, f'Ответ на ваш вопрос: {body.answer}')
    return {'program': doc.model_dump(mode='json'), 'comment': c.model_dump()}


class ReviewIn(BaseModel):
    module_id: str
    decision: Literal['accept', 'return', 'question', 'accept_item']
    comment: str = ''
    node_id: str = ''
    score: int | None = Field(None, ge=1, le=5)


@router.post('/{program_id}/reviews/decision', summary='Эксперт принимает модуль или возвращает его методисту')
async def review_decision(program_id: str, body: ReviewIn, p: Principal = Depends(require('expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.review_decision(doc, body.module_id, p.user_id, body.decision, body.comment, body.node_id, body.score)
    await svc.save(doc, p.user_id)
    m = doc.module_by_id(body.module_id)
    what = {'accept': 'принял модуль', 'return': 'вернул модуль', 'question': 'задал вопрос по модулю', 'accept_item': f'проверил элемент {body.node_id} модуля'}[body.decision]
    text = f'Эксперт {what} {m.n if m else body.module_id}' + (f' · оценка {body.score} из 5' if body.score and body.decision == 'accept' else '') + (f': {body.comment}' if body.comment else '')
    await svc.log_event(program_id, p.user_id, f'review_{body.decision}', text, node_id=body.node_id or body.module_id)
    m = doc.module_by_id(body.module_id)
    if body.decision == 'accept_item' and m and m.review_status != 'accepted':
        return {'program': doc.model_dump(mode='json')}
    verdict = {'accept': 'принят', 'accept_item': 'принят', 'return': 'возвращён', 'question': 'вопрос'}[body.decision]
    await svc.notify(await svc.owner_of(program_id), program_id, f'{p.name}: модуль {m.n if m else body.module_id} «{m.title if m else ""}» — {verdict}')
    return {'program': doc.model_dump(mode='json')}


@router.post('/{program_id}/submit', summary='Отправить программу на утверждение')
async def submit(program_id: str, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.submit(doc, p.user_id)
    await svc.save(doc, p.user_id, reason='на утверждении', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'submitted', 'Программа отправлена руководителю')
    for head in svc.head_ids():
        await svc.notify(head, program_id, f'Программа «{doc.title}» на утверждении')
    return {'status': doc.status.value}


@router.post('/{program_id}/approval', summary='Руководитель утверждает программу или возвращает с комментарием')
async def approval(program_id: str, body: ApproveIn, p: Principal = Depends(require('head'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.head_decision(doc, p.user_id, body.decision, body.comment)
    await svc.save(doc, p.user_id, reason='решение руководителя', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'approved' if body.decision == 'approve' else 'returned', body.comment)
    await svc.notify(await svc.owner_of(program_id), program_id, 'Программа утверждена: проект приказа готов' if body.decision == 'approve' else f'Программа возвращена: {body.comment}')
    return {'status': doc.status.value}


@router.get('/{program_id}/export/{fmt}', summary='Выгрузка: docx, pptx, gift, moodle_xml, json, order_draft, lectures_docx')
async def export_file(program_id: str, fmt: str, p: Principal = Depends(current_principal)) -> Response:
    if p.role == 'expert':
        raise ForbiddenRole('Эксперт читает свои модули на экране вычитки; выгрузка программы — у методиста и руководителя')
    doc = await _load_for(program_id, p)
    content, media, filename = export.render(doc, fmt)
    from urllib.parse import quote

    return Response(content=content, media_type=media, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get('/{program_id}/events', summary='Журнал событий программы')
async def events(program_id: str, p: Principal = Depends(require('methodist', 'head'))) -> list[dict[str, Any]]:
    return await svc.events(program_id)


@misc.get('/jobs/{job_id}', summary='Статус задания: queued, running, done, failed')
async def job(job_id: str, request: Request, p: Principal = Depends(current_principal)) -> dict[str, Any]:
    info = await svc.get_job(job_id)
    doc = await _load_for(info['program_id'], p)
    if info['status'] == 'done' and info['kind'] == 'auto':
        # Результат автопрогона в том же виде, что и при wait=true (таблица 21)
        info['result'] = _auto_response(doc, str(request.base_url).rstrip('/'))
    elif info['status'] == 'done':
        info['result'] = {'program_id': doc.id, 'status': doc.status.value, 'version': doc.version}
    return info


@misc.get('/reviews', summary='Задания на вычитку текущего эксперта')
async def my_reviews(p: Principal = Depends(require('expert'))) -> list[dict[str, Any]]:
    return await _reviews_of(p.user_id)


async def _reviews_of(user_id: str) -> list[dict[str, Any]]:
    """Задания на вычитку (ReviewTask, таблица 18): rid = program_id__module_id."""
    out = []
    for item in await svc.list_programs():
        doc = await svc.load(item['id'])
        for m in doc.modules:
            if m.expert_id == user_id:
                total, done = wf.review_items(doc, m.id)
                out.append({
                    'rid': f'{doc.id}__{m.id}', 'program_id': doc.id, 'program': doc.title, 'module_id': m.id, 'n': m.n, 'title': m.title,
                    'status': m.review_status, 'hours': m.hours.total, 'items_total': total, 'items_done': done,
                })
    return out


def _rid(rid: str) -> tuple[str, str]:
    program_id, sep, module_id = rid.partition('__')
    if not sep:
        raise BadRequest('Идентификатор задания на вычитку: program_id__module_id')
    return program_id, module_id


class ReviewCommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    node_id: str = ''
    ask_agent: bool = False


@misc.post('/reviews/{rid}/comments', summary='Комментарий к фрагменту задания на вычитку; ask_agent=true — запрос правки агенту')
async def review_comment(rid: str, body: ReviewCommentIn, p: Principal = Depends(require('expert', 'methodist'))) -> dict[str, Any]:
    program_id, module_id = _rid(rid)
    return await comment(program_id, CommentIn(module_id=module_id, text=body.text, node_id=body.node_id, ask_agent=body.ask_agent), p)


class ReviewDecisionIn(BaseModel):
    decision: Literal['accept', 'return', 'question', 'accept_item']
    comment: str = ''
    node_id: str = ''
    score: int | None = Field(None, ge=1, le=5)


@misc.post('/reviews/{rid}/decision', summary='Принять элемент или модуль, вернуть модуль методисту')
async def review_rid_decision(rid: str, body: ReviewDecisionIn, p: Principal = Depends(require('expert'))) -> dict[str, Any]:
    program_id, module_id = _rid(rid)
    return await review_decision(program_id, ReviewIn(module_id=module_id, decision=body.decision, comment=body.comment, node_id=body.node_id, score=body.score), p)


@misc.get('/notifications', summary='Уведомления текущего пользователя')
async def my_notifications(p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    return await svc.notifications(p.user_id)


class ReadIn(BaseModel):
    ids: list[int] = Field(default_factory=list)


@misc.post('/notifications/read', summary='Отметить уведомления прочитанными (все или по списку id)')
async def read_notifications(body: ReadIn, p: Principal = Depends(current_principal)) -> dict[str, int]:
    return {'marked': await svc.mark_read(p.user_id, body.ids or None)}
