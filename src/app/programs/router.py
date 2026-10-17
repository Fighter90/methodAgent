"""Методы API /api/v1 (ТЗ, таблица 19) и контракт автопрогона POST /programs?mode=auto."""

from __future__ import annotations

import base64
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.agent import workflow as wf
from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import BadRequest, Conflict, ForbiddenRole
from app.core.security import Principal, current_principal, require, users
from app.export import service as export
from app.kb.files import parse_reference
from app.programs import service as svc
from app.programs.schemas import Assumption, ProgramDoc, ReferenceInfo, Status

router = APIRouter(prefix='/programs', tags=['programs'])
misc = APIRouter(tags=['misc'])


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
        refs.append(ReferenceInfo(name=name, chars=len(parsed.text), structure=parsed.structure, hours_issues=parsed.hours_issues, text_sample=parsed.text[:20000]))
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
        'kit': doc.model_dump(mode='json', include={'kit', 'sources', 'norm_base', 'profstandard'}),
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
    try:
        wf.approve_skeleton(doc, 'auto-approve', auto=True)
    except Conflict:
        doc.agent_notes.append('Каркас содержит ошибки ✕ — в режиме auto комплект собран со статусом done_with_errors')
        doc.status = Status.SKELETON_APPROVED
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
            await svc.save(doc, p.user_id)
            job_id = await svc.create_job(doc.id, 'auto')

            async def _job(progress):  # noqa: ANN001
                d = await svc.load(doc.id)
                await _auto_pipeline(d, p.user_id)

            svc.run_job(job_id, _job)
            return {'program_id': doc.id, 'job_id': job_id, 'status': 'queued'}
        doc = await _auto_pipeline(doc, p.user_id)
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


def _skeleton_job(program_id: str, owner: str, comment: str = ''):
    async def _job(progress):  # noqa: ANN001
        await progress({'step': 'skeleton', 'text': 'Собираю каркас: компетенции, модули, темы, часы'})
        d = await svc.load(program_id)
        await wf.skeleton_step(d, comment)
        await svc.save(d, owner, reason='каркас', snapshot=True)
        await svc.log_event(program_id, 'agent', 'skeleton_built', f'Каркас за {d.timing_s.get("skeleton", 0)} с', version=d.version)

    return _job


@router.get('', summary='Список программ')
async def list_programs(p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    return await svc.list_programs()


@router.get('/{program_id}', summary='Состояние программы: вопросы, каркас или комплект в JSON')
async def get_program(program_id: str, p: Principal = Depends(current_principal)) -> dict[str, Any]:
    doc = await svc.load(program_id)
    data = doc.model_dump(mode='json')
    if p.role == 'expert':
        mine = {m.id for m in doc.modules if m.expert_id == p.user_id}
        data['modules'] = [m for m in data['modules'] if m['id'] in mine]
    data['readiness'] = wf.readiness(doc)
    data['totals'] = doc.totals().model_dump()
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
    await svc.log_event(program_id, p.user_id, 'skeleton_patch', str(body)[:500])
    return {'program': doc.model_dump(mode='json'), 'totals': doc.totals().model_dump()}


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
    job_id = await svc.create_job(program_id, 'kit')

    async def _job(progress):  # noqa: ANN001
        d = await svc.load(program_id)
        await wf.generate_kit(d, progress)
        await svc.save(d, p.user_id, reason='комплект', snapshot=True)
        await svc.log_event(program_id, 'agent', 'kit_ready', f'Блокирующие проверки {d.report.blocking_passed}/10' if d.report else '', version=d.version)

    svc.run_job(job_id, _job)
    return {'job_id': job_id, 'status': 'queued'}


@router.get('/{program_id}/report', summary='Отчёт автопроверки и матрица покрытия')
async def report(program_id: str, p: Principal = Depends(require('methodist', 'head', 'api', 'expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    return doc.report.model_dump() if doc.report else {}


class EditIn(BaseModel):
    target: str
    instruction: str = ''
    new_title: str = ''
    dry_run: bool = False


@router.post('/{program_id}/edits', summary='Точечная правка; dry_run=true — только список затрагиваемых элементов')
async def edits(program_id: str, body: EditIn, p: Principal = Depends(require('methodist', 'expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    if p.role == 'expert':
        allowed = {m.id for m in doc.modules if m.expert_id == p.user_id}
        owner_module = next((m.id for m in doc.modules if any(t.id == body.target for t in m.topics)), None)
        owner_module = owner_module or next((x.module_id for x in [*doc.kit.questions, *doc.kit.tasks] if x.id == body.target), None)
        if owner_module not in allowed:
            raise ForbiddenRole('Эксперт правит только свои модули')
    result = await wf.edit(doc, body.target, body.instruction, body.new_title, body.dry_run)
    if not body.dry_run:
        await svc.save(doc, p.user_id, reason=f'правка {body.target}', snapshot=True)
        await svc.log_event(program_id, p.user_id, 'edit', f'{body.target}: {body.instruction}', node_id=body.target, version=doc.version)
    return {**result, 'program': doc.model_dump(mode='json')}


@router.get('/{program_id}/versions', summary='Версии комплекта')
async def versions(program_id: str, p: Principal = Depends(require('methodist', 'head'))) -> list[dict[str, Any]]:
    return await svc.versions(program_id)


@router.post('/{program_id}/versions/{version}/restore', summary='Откат к версии')
async def restore(program_id: str, version: int, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.version_doc(program_id, version)
    await svc.save(doc, p.user_id, reason=f'откат к версии {version}', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'restore', f'Откат к версии {version}', version=doc.version)
    return {'version': doc.version}


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
    from app.skills.review_assist.run import propose

    doc = await svc.load(program_id)
    proposal = await propose(doc, body.module_id, body.node_id, body.text) if body.ask_agent else ''
    c = wf.add_comment(doc, body.module_id, p.user_id, body.text, body.node_id, proposal)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, 'comment', body.text, node_id=body.node_id)
    await svc.notify('u-madina', program_id, f'{p.name}: {body.text[:120]}')
    return {'comment': c.model_dump()}


class AnswerIn(BaseModel):
    comment_id: str
    answer: str = ''
    apply_proposal: bool = False


@router.post('/{program_id}/comments/answer', summary='Ответ методиста или применение предложения агента')
async def answer_comment(program_id: str, body: AnswerIn, p: Principal = Depends(require('methodist', 'expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    c = next((x for x in doc.comments if x.id == body.comment_id), None)
    if c is None:
        raise BadRequest('Комментарий не найден')
    if body.apply_proposal and c.node_id:
        await wf.edit(doc, c.node_id, c.agent_proposal or c.text)
        c.status = 'applied'
    else:
        c.answer, c.status = body.answer, 'answered'
    m = doc.module_by_id(c.module_id)
    if m and m.review_status == 'question':
        m.review_status = 'in_review'
    await svc.save(doc, p.user_id, reason='ответ на вопрос эксперта', snapshot=body.apply_proposal)
    await svc.log_event(program_id, p.user_id, 'comment_answer', body.answer or 'Правка агента применена')
    if c.author:
        await svc.notify(c.author, program_id, f'Ответ на ваш вопрос: {body.answer or "агент внёс правку"}')
    return {'program': doc.model_dump(mode='json')}


class ReviewIn(BaseModel):
    module_id: str
    decision: Literal['accept', 'return', 'question']
    comment: str = ''


@router.post('/{program_id}/reviews/decision', summary='Эксперт принимает модуль или возвращает его методисту')
async def review_decision(program_id: str, body: ReviewIn, p: Principal = Depends(require('expert'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.review_decision(doc, body.module_id, p.user_id, body.decision, body.comment)
    await svc.save(doc, p.user_id)
    await svc.log_event(program_id, p.user_id, f'review_{body.decision}', body.comment, node_id=body.module_id)
    await svc.notify('u-madina', program_id, f'{p.name}: модуль {body.module_id} — {body.decision}')
    return {'program': doc.model_dump(mode='json')}


@router.post('/{program_id}/submit', summary='Отправить программу на утверждение')
async def submit(program_id: str, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.submit(doc, p.user_id)
    await svc.save(doc, p.user_id, reason='на утверждении', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'submitted', 'Программа отправлена руководителю')
    await svc.notify('u-ahmed', program_id, f'Программа «{doc.title}» на утверждении')
    return {'status': doc.status.value}


@router.post('/{program_id}/approval', summary='Руководитель утверждает программу или возвращает с комментарием')
async def approval(program_id: str, body: ApproveIn, p: Principal = Depends(require('head'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    wf.head_decision(doc, p.user_id, body.decision, body.comment)
    await svc.save(doc, p.user_id, reason='решение руководителя', snapshot=True)
    await svc.log_event(program_id, p.user_id, 'approved' if body.decision == 'approve' else 'returned', body.comment)
    await svc.notify('u-madina', program_id, 'Программа утверждена: проект приказа готов' if body.decision == 'approve' else f'Программа возвращена: {body.comment}')
    return {'status': doc.status.value}


@router.get('/{program_id}/export/{fmt}', summary='Выгрузка: docx, pptx, gift, moodle_xml, json, order_draft, lectures_docx')
async def export_file(program_id: str, fmt: str, p: Principal = Depends(current_principal)) -> Response:
    doc = await svc.load(program_id)
    content, media, filename = export.render(doc, fmt)
    from urllib.parse import quote

    return Response(content=content, media_type=media, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get('/{program_id}/events', summary='Журнал событий программы')
async def events(program_id: str, p: Principal = Depends(require('methodist', 'head', 'expert'))) -> list[dict[str, Any]]:
    return await svc.events(program_id)


@misc.get('/jobs/{job_id}', summary='Статус задания: queued, running, done, failed')
async def job(job_id: str, p: Principal = Depends(current_principal)) -> dict[str, Any]:
    return await svc.get_job(job_id)


@misc.get('/reviews', summary='Задания на вычитку текущего эксперта')
async def my_reviews(p: Principal = Depends(require('expert'))) -> list[dict[str, Any]]:
    out = []
    for item in await svc.list_programs():
        doc = await svc.load(item['id'])
        for m in doc.modules:
            if m.expert_id == p.user_id:
                out.append({'program_id': doc.id, 'program': doc.title, 'module_id': m.id, 'n': m.n, 'title': m.title, 'status': m.review_status, 'hours': m.hours.total})
    return out


@misc.get('/notifications', summary='Уведомления текущего пользователя')
async def my_notifications(p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    return await svc.notifications(p.user_id)
