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
async def diff(program_id: str, a: int, b: int, p: Principal = Depends(require('methodist', 'head'))) -> dict[str, Any]:
    da = await svc.version_doc(program_id, a)
    db = await svc.version_doc(program_id, b)
    return extras.diff(da, db)


@router.get('/programs/{program_id}/sandbox', summary='Примеры кода: запуск в песочнице, версии библиотек, время (FR-46)')
async def sandbox(program_id: str, p: Principal = Depends(require('methodist', 'expert', 'head'))) -> dict[str, Any]:
    import asyncio

    doc = await svc.load(program_id)
    if p.role == 'expert':
        # Эксперт видит запуск примеров только своих модулей (FR-44, FR-46)
        mine = {m.id for m in doc.modules if m.expert_id == p.user_id}
        doc = doc.model_copy(deep=True)
        doc.kit.lectures = [lec for lec in doc.kit.lectures if lec.module_id in mine]
    return await asyncio.to_thread(extras.sandbox_report, doc)


@router.get('/programs/{program_id}/sections', summary='Текст программы по разделам шаблона АЦР в порядке выгрузки')
async def sections(program_id: str, p: Principal = Depends(current_principal)) -> list[dict[str, Any]]:
    from app.programs.router import _load_for

    doc = await _load_for(program_id, p)
    texts = doc.kit.sections or (build_sections(doc) if doc.modules else {})
    return [{'key': k, 'title': t, 'level': lvl, 'text': '' if k in GROUP_KEYS else texts.get(k, '')} for k, t, lvl in sections_for(doc)]


@router.get('/me/tasks', summary='Число задач по каждой роли пользователя для переключателя ролей (FR-63)')
async def my_tasks(p: Principal = Depends(current_principal)) -> dict[str, Any]:
    if p.anonymous:
        from app.core.errors import Unauthorized

        raise Unauthorized('Нужен вход')
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
    from app.kb import norms

    hits = await orgdocs.search(body.query, body.k) + norms.search(body.query, k=body.k)
    return sorted(hits, key=lambda h: -h['score'])[: body.k]


@router.get('/kb/norms', summary='Нормативная база знаний: выжимки НПА, ФГОС и рекомендаций с источником и датой проверки')
async def kb_norms(p: Principal = Depends(require('admin', 'methodist', 'head', 'expert'))) -> dict[str, Any]:
    from app.kb import norms
    from app.kb.registry import registry

    reg = registry()
    return {'documents': [norms.public(d) for d in norms.norms()],
            'counts': {'npa': len(reg['npa']), 'ps': len(reg['ps']), 'fgos': len(reg.get('fgos', [])), 'literature': len(reg['literature'])}}


# --- Профиль организации и реестр (администратор, таблица 19) ---
_PROFILE_KEYS = {'name', 'header', 'requisites', 'address', 'city', 'order_prefix', 'norm_mode', 'defaults', 'experts', 'head',
                 'methodists', 'notify_email', 'smtp', 'templates', 'note', 'checked_at', 'samples'}
_DEFAULT_KEYS = {'program_type', 'volume_h', 'audience', 'form', 'final_assessment_form', 'questions_per_test'}
_REGISTRY_REQUIRED = {'ps': {'code', 'title'}, 'npa': {'id', 'bibl'}, 'tools': {'current', 'outdated'}, 'literature': {'bibl'}}


@router.get('/org/profile', summary='Профиль организации: шаблоны, значения по умолчанию, эксперты, уведомления')
async def org_profile_get(p: Principal = Depends(require('admin', 'methodist', 'head'))) -> dict[str, Any]:
    from app.kb.registry import org_profile

    prof = dict(org_profile())
    if p.role != 'admin':
        prof.pop('smtp', None)
    return prof


@router.put('/org/profile', summary='Изменить профиль организации (администратор)')
async def org_profile_put(body: dict[str, Any], p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    from datetime import date

    from app.kb.registry import org_profile, save_override

    unknown = set(body) - _PROFILE_KEYS
    if unknown:
        raise BadRequest(f'Неизвестные поля профиля: {", ".join(sorted(unknown))}', details={'allowed': sorted(_PROFILE_KEYS)})
    if 'defaults' in body and (bad := set(body['defaults'] or {}) - _DEFAULT_KEYS):
        raise BadRequest(f'Неизвестные значения по умолчанию: {", ".join(sorted(bad))}', details={'allowed': sorted(_DEFAULT_KEYS)})
    if 'smtp' in body and 'password' in (body['smtp'] or {}):
        raise BadRequest('Пароль SMTP в профиле не хранится: задайте переменную окружения SMTP_PASSWORD')
    merged = {**org_profile(), **body, 'checked_at': date.today().isoformat()}
    save_override('org', merged)
    await svc.log_event('org', p.user_id, 'org_profile', ', '.join(sorted(body)), version=0)
    return merged


class RegistryIn(BaseModel):
    kind: str = Field(description='ps, npa, tools или literature')
    items: list[dict[str, Any]] | dict[str, Any] = Field(description='список записей; для tools — объект реестра версий')


@router.get('/org/registry', summary='Реестр ПС, НПА, версий инструментов и литературы с датой проверки')
async def org_registry_get(kind: str = 'ps', p: Principal = Depends(require('admin', 'methodist', 'head'))) -> Any:
    from app.kb.registry import registry

    if kind == 'fgos':
        return registry().get('fgos', [])
    if kind not in _REGISTRY_REQUIRED:
        raise BadRequest('kind: ps, npa, fgos, tools или literature')
    return registry()[kind]


@router.put('/org/registry', summary='Заменить раздел реестра ПС, НПА, версий или литературы (администратор)')
async def org_registry_put(body: RegistryIn, p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    from datetime import date

    from app.kb.registry import save_override

    need = _REGISTRY_REQUIRED.get(body.kind)
    if need is None:
        raise BadRequest('kind: ps, npa, tools или literature')
    if body.kind == 'tools':
        if not isinstance(body.items, dict) or not {'current', 'outdated'} <= set(body.items):
            raise BadRequest('Реестр версий — объект с полями current и outdated')
        body.items['checked_at'] = date.today().isoformat()
    elif not isinstance(body.items, list) or not body.items:
        raise BadRequest('Нужен непустой список записей')
    else:
        for i, item in enumerate(body.items, 1):
            if missing := need - set(item):
                raise BadRequest(f'Запись {i}: нет полей {", ".join(sorted(missing))}')
            item.setdefault('checked_at', date.today().isoformat())
    save_override(body.kind, body.items)
    await svc.log_event('org', p.user_id, 'org_registry', f'{body.kind}: {len(body.items)} записей', version=0)
    return {'kind': body.kind, 'items': len(body.items)}


@router.post('/org/documents', summary='Документ организации в базу знаний (администратор); то же, что POST /kb/documents')
async def org_documents(file: UploadFile = File(...), kind: str = Form('other'), p: Principal = Depends(require('admin'))) -> dict[str, Any]:
    return await kb_upload(file, kind, p)


@router.get('/programs/{program_id}/experts', summary='Эксперты профиля с подсказкой агента по каждому модулю (FR-39)')
async def suggest_experts(program_id: str, p: Principal = Depends(require('methodist', 'head'))) -> dict[str, Any]:
    doc = await svc.load(program_id)
    return extras.suggest_experts(doc)
