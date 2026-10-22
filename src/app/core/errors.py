"""Ошибки API в едином формате {"code", "message_ru", "details"} (ТЗ, таблица 20)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Базовое исключение приложения."""

    status_code = 500
    code = 'INTERNAL_ERROR'

    def __init__(self, message_ru: str, *, details: dict[str, Any] | None = None, code: str | None = None) -> None:
        self.message_ru = message_ru
        self.details = details or {}
        if code:
            self.code = code
        super().__init__(message_ru)


class BadRequest(AppError):
    status_code = 400
    code = 'BAD_REQUEST'


class Unauthorized(AppError):
    status_code = 401
    code = 'UNAUTHORIZED'


class ForbiddenRole(AppError):
    status_code = 403
    code = 'FORBIDDEN_ROLE'


class NotFound(AppError):
    status_code = 404
    code = 'NOT_FOUND'


class Conflict(AppError):
    """Действие недоступно в текущем состоянии (правила блокировки, таблица 11)."""

    status_code = 409
    code = 'STATE_CONFLICT'


class PayloadTooLarge(AppError):
    """Вложение или тело запроса больше допустимого — отклоняется до декодирования."""

    status_code = 413
    code = 'PAYLOAD_TOO_LARGE'


class UnsupportedMedia(AppError):
    """Тип файла вне белого списка или содержимое не соответствует расширению."""

    status_code = 415
    code = 'UNSUPPORTED_MEDIA_TYPE'


class RateLimited(AppError):
    status_code = 429
    code = 'RATE_LIMIT'


def _body(code: str, message_ru: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'code': code, 'message_ru': message_ru, 'details': details or {}}


def register_error_handlers(app: FastAPI) -> None:
    """Подключает обработчики, которые не раскрывают внутренние детали."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message_ru, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{'loc': list(e.get('loc', [])), 'msg': e.get('msg', '')} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=_body('VALIDATION_ERROR', 'Тело запроса не соответствует схеме', {'errors': errors}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        import logging

        logging.getLogger('app').exception('Необработанная ошибка: %s', type(exc).__name__)
        return JSONResponse(status_code=500, content=_body('INTERNAL_ERROR', 'Внутренняя ошибка сервера'))
