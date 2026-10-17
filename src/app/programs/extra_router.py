"""Методы сверх основного потока: шаблон, адаптация, актуализация, версии, песочница, задачи по ролям, база знаний."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from app.agent import extras
from app.agent.sections import build_sections
from app.core.config import get_settings
from app.core.errors import BadRequest
from app.core.security import Principal, current_principal, require, users
from app.kb import orgdocs
from app.kb.files import parse_reference
from app.programs import service as svc
from app.validation.rules import GROUP_KEYS, sections_for

router = APIRouter(tags=['extras'])


class TemplateIn(BaseModel):
    program_type: str = Field(description='dpp_pk, dpp_pk_internship или doop')


@router.post('/programs/{program_id}/template', summary='Сменить шаблон АЦР до утверждения каркаса (FR-06)')
async def change_template(program_id: str, body: TemplateIn, p: Principal = Depends(require('methodist'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    old = doc.template
    extras.change_template(doc, body.program_type)
    await svc.save(doc, p.user_id, reason=f'шаблон: {doc.template}', snapshot=bool(doc.modules))
    await svc.log_event(program_id, p.user_id, 'template', f'{old} → {doc.template}', version=doc.version)
    return {'program': doc.model_dump(mode='json')}


class AdaptIn(BaseModel):
    volume_h: int | None = Field(default=None, ge=8, le=2000)
    audience: str = Field(default='', max_length=300)
    title: str = Field(default='', max_length=200)
    duration_weeks: float | None = Field(default=None, gt=0, le=104)


@router.post('/programs/{program_id}/adapt', summary='Адаптация: новая программа для другой аудитории или объёма (FR-60)')
async def adapt(program_id: str, body: AdaptIn, p: Principal = Depends(require('methodist', 'api'))) -> dict[str, Any]:
    src = await svc.load(program_id)
    doc = extras.adapt(src, svc.new_id('prg'), volume_h=body.volume_h, audience=body.audience, title=body.title, duration_weeks=body.duration_weeks)
    await svc.save(doc, p.user_id, reason=f'адаптация из {src.id}', snapshot=True)
    await svc.log_event(doc.id, p.user_id, 'created', f'Адаптация программы «{src.title}»', version=doc.version)
    await svc.log_event(src.id, p.user_id, 'adapted', f'На её основе создана программа {doc.id}')
    return {'program_id': doc.id, 'status': doc.status.value, 'program': doc.model_dump(mode='json')}


@router.get('/programs/{program_id}/actualize', summary='Актуализация: устаревшие темы, инструменты и версии по реестру (FR-61)')
async def actualize_program(program_id: str, p: Principal = Depends(require('methodist', 'expert', 'head', 'api'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    found = extras.actualize_doc(doc)
    return {'program_id': doc.id, 'findings': found, 'total': len(found), 'registry_checked_at': extras.tools().get('checked_at', '')}


@router.post('/actualize', summary='Актуализация старой программы из файла (.docx, .pdf, .txt) без создания черновика')
async def actualize_file(file: UploadFile = File(...), p: Principal = Depends(require('methodist', 'api'))) -> dict[str, Any]:
    content = await file.read()
    if len(content) > get_settings().max_file_size_bytes:
        raise BadRequest('Файл больше допустимого размера')
    parsed = parse_reference(file.filename or 'file', content)
    found = extras.scan_text(parsed.text)
    return {'name': file.filename, 'chars': len(parsed.text), 'structure': parsed.structure[:40], 'findings': found, 'total': len(found)}


@router.get('/programs/{program_id}/versions/{a}/diff/{b}', summary='Сравнение двух версий комплекта (FR-38)')
async def diff(program_id: str, a: int, b: int, p: Principal = Depends(require('methodist', 'head', 'expert'))) -> dict[str, Any]:
    da = await svc.version_doc(program_id, a)
    db = await svc.version_doc(program_id, b)
    return extras.diff(da, db)


@router.get('/programs/{program_id}/sandbox', summary='Примеры кода: запуск в песочнице, версии библиотек, время (FR-46)')
async def sandbox(program_id: str, p: Principal = Depends(require('methodist', 'expert', 'head'))) -> dict[str, Any]:
    import asyncio

    doc = await svc.load(program_id)
    return await asyncio.to_thread(extras.sandbox_report, doc)


@router.get('/programs/{program_id}/sections', summary='Текст программы по разделам шаблона АЦР в порядке выгрузки')
async def sections(program_id: str, p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    doc = await svc.load(program_id)
    texts = doc.kit.sections or (build_sections(doc) if doc.modules else {})
    return [{'key': k, 'title': t, 'level': lvl, 'text': '' if k in GROUP_KEYS else texts.get(k, '')} for k, t, lvl in sections_for(doc)]


@router.get('/me/tasks', summary='Число задач по каждой роли пользователя для переключателя ролей (FR-63)')
async def my_tasks(p: Principal = Depends(current_principal)) -> dict[str, Any]:
    docs = [await svc.load(x['id']) for x in await svc.list_programs()]
    demo = {'methodist': 'u-madina', 'expert': 'u-timur', 'head': 'u-ahmed'}
    out = {}
    for role, uid in demo.items():
        me = p.user_id if p.role == role else uid
        out[role] = extras.tasks_for(docs, me, role)
    me_user = users().get(p.user_id)
    return {'user_id': p.user_id, 'roles': list(me_user.roles) if me_user else [p.role], 'tasks': out}


# --- База знаний организации (FR-09) ---
@router.get('/kb/documents', summary='Документы организации в базе знаний')
async def kb_list(p: Principal = Depends(require('admin', 'methodist', 'head'))) -> list[dict[str, Any]]:
    return orgdocs.list_documents()


@router.post('/kb/documents', summary='Загрузить шаблон, положение или иной документ организации (администратор)')
async def kb_upload(file: UploadFile = File(...), kind: str = Form('other'), p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    content = await file.read()
    if len(content) > get_settings().max_file_size_bytes:
        raise BadRequest('Файл больше допустимого размера')
    return await orgdocs.add_document(file.filename or 'document', content, kind, p.user_id)


@router.delete('/kb/documents/{doc_id}', summary='Удалить документ из базы знаний (администратор)')
async def kb_delete(doc_id: str, p: Principal = Depends(require('admin'))) -> dict[str, str]:
    orgdocs.delete_document(doc_id)
    return {'status': 'deleted'}


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)


@router.post('/kb/search', summary='Поиск по базе знаний: эмбеддинги шлюза или пересечение слов')
async def kb_search(body: SearchIn, p: Principal = Depends(require('admin', 'methodist', 'head', 'expert'))) -> list[dict[str, Any]]:
    return await orgdocs.search(body.query, body.k)
