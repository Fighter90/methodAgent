"""Точка входа: FastAPI-приложение МетодАгента (API /api/v1 и интерфейс SPA)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.config import ROOT_DIR, get_settings
from app.core.db import init_db
from app.core.errors import Unauthorized, register_error_handlers
from app.core.security import create_token, users, verify_password
from app.llm.client import get_llm
from app.programs.extra_router import router as extra_router
from app.programs.router import misc
from app.programs.router import router as programs_router
from app.skills.base import load_skills

logger = logging.getLogger('metodagent')
STATIC_DIR = ROOT_DIR / 'frontend' / 'dist'


class LoginIn(BaseModel):
    user_id: str
    password: str = 'demo'
    role: str | None = None


auth = APIRouter(prefix='/auth', tags=['auth'])


@auth.post('/login', summary='Вход демо-пользователя (пароль demo): токен с ролью')
async def login(body: LoginIn) -> dict:
    u = users().get(body.user_id)
    if u is None or not verify_password(body.password, u.password_hash):
        raise Unauthorized('Неверный логин или пароль')
    role = body.role or u.roles[0]
    if role not in u.roles:
        raise Unauthorized('У пользователя нет такой роли')
    return {'access_token': create_token(u.id, role), 'token_type': 'bearer', 'user': {'id': u.id, 'name': u.name, 'role': role, 'title': u.title}}


@auth.get('/users', summary='Демо-пользователи для переключателя ролей')
async def demo_users() -> list[dict]:
    return [{'id': u.id, 'name': u.name, 'roles': list(u.roles), 'title': u.title} for u in users().values()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    s.data_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info('МетодАгент запущен: LLM %s, навыков %d', 'включена' if s.llm_enabled else 'выключена (резервная генерация)', len(load_skills()))
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title='МетодАгент API',
        version=s.app_version,
        description='Агент методиста: из запроса — каркас и полный комплект ДПП/ДООП с автопроверкой по 27 правилам.',
        docs_url='/docs' if s.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
    register_error_handlers(app)

    api = APIRouter(prefix=s.api_v1_prefix)
    api.include_router(auth)
    api.include_router(programs_router)
    api.include_router(misc)
    api.include_router(extra_router)

    @api.get('/llm/status', tags=['misc'], summary='Доступность LLM-шлюза и выбранные модели')
    async def llm_status() -> dict:
        info = await get_llm().ping()
        llm = get_llm()
        info['spent_today_rub'] = round(llm.spent_today(), 2)
        info['daily_budget_rub'] = s.llm_daily_budget_rub
        info['daily_limit_reached'] = llm.limit_reached()
        return {**info, 'models': {'generate': s.llm_model_generate, 'judge': s.llm_model_judge, 'embed': s.llm_model_embed}, 'judge_enabled': s.llm_judge_enabled}

    @api.get('/skills', tags=['misc'], summary='Навыки агента (SKILL.md)')
    async def skills() -> list[dict]:
        return [{'name': k, **{x: v.get(x) for x in ('description', 'version')}} for k, v in load_skills().items()]

    app.include_router(api)

    @app.get('/health', tags=['misc'])
    async def health() -> dict:
        return {'status': 'ok', 'version': s.app_version, 'llm': s.llm_enabled}

    if (STATIC_DIR / 'index.html').exists():
        app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        async def spa(path: str):
            f = STATIC_DIR / path
            if path and f.is_file() and STATIC_DIR in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(STATIC_DIR / 'index.html')
    else:

        @app.get('/', include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({'app': 'МетодАгент', 'docs': '/docs', 'api': s.api_v1_prefix})

    return app


app = create_app()
_ = Path
