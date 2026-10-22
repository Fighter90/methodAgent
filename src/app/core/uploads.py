"""Приём вложений: тип и размер проверяются до декодирования и чтения в память (замечание прогона 22.10).

Три рубежа: ASGI-слой `BodyLimit` режет тело запроса сверх общего предела (413) ещё до разбора JSON
и multipart; `decode_base64` и `read_upload` проверяют размер одного файла по длине base64 и потоково
по порциям (413); `check_type` сверяет расширение с белым списком и с сигнатурой содержимого (415).
"""

from __future__ import annotations

import base64
import binascii
import json
from pathlib import PurePath
from typing import Any

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import BadRequest, PayloadTooLarge, UnsupportedMedia

ALLOWED_EXT = {'.docx': 'docx', '.pdf': 'pdf', '.txt': 'txt', '.md': 'txt'}
_CHUNK = 1024 * 1024
_WS = str.maketrans('', '', ' \t\r\n')


def check_name(name: str) -> None:
    """Расширение из белого списка; файл без расширения допускается — тип решит сигнатура."""
    ext = PurePath(name).suffix.lower()
    if ext and ext not in ALLOWED_EXT:
        raise UnsupportedMedia(f'Файл «{name}»: формат {ext} не поддерживается — принимаются .docx, .pdf, .txt и .md')


def check_type(name: str, content: bytes, fmt: str | None) -> None:
    """Пустой файл — 400; содержимое не того типа, что заявлено расширением, — 415."""
    if not content:
        raise BadRequest(f'Файл «{name}» пустой')
    check_name(name)
    ext = PurePath(name).suffix.lower()
    if fmt is None:
        raise UnsupportedMedia(f'Файл «{name}»: неподдерживаемый формат — принимаются .docx, .pdf и текст')
    if ext and ALLOWED_EXT[ext] != fmt:
        raise UnsupportedMedia(f'Файл «{name}»: содержимое не соответствует расширению {ext}')


def _too_large(name: str) -> PayloadTooLarge:
    s = get_settings()
    return PayloadTooLarge(f'Файл «{name}» больше {s.max_file_size_mb} МБ — уменьшите вложение или пришлите ссылкой')


def decode_base64(name: str, data: str) -> bytes:
    """Размер по длине base64 до декодирования; переносы строк и префикс data: допускаются."""
    check_name(name)
    if data.startswith('data:') and ',' in data[:200]:
        data = data.split(',', 1)[1]
    data = data.translate(_WS)
    if not data:
        raise BadRequest(f'Файл «{name}»: вложение пустое')
    if len(data) * 3 // 4 > get_settings().max_file_size_bytes:
        raise _too_large(name)
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequest(f'Файл «{name}»: неверный base64') from exc


async def read_upload(f: UploadFile) -> bytes:
    """Файл из multipart читается порциями и обрывается на пределе — целиком в память не поднимается."""
    name = f.filename or 'file'
    check_name(name)
    limit = get_settings().max_file_size_bytes
    if f.size is not None and f.size > limit:
        raise _too_large(name)
    parts, total = [], 0
    while chunk := await f.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise _too_large(name)
        parts.append(chunk)
    return b''.join(parts)


def body_limit_bytes() -> int:
    """Предел тела: все вложения в base64 (+37 %) и запас 1 МБ на текст и поля формы."""
    s = get_settings()
    return s.max_files_per_request * s.max_file_size_bytes * 137 // 100 + _CHUNK


class BodyLimit:
    """ASGI-слой: 413 до разбора тела приложением.

    С Content-Length решение принимается по заголовку (сервер не отдаст больше заявленного);
    тело без длины (chunked) дочитывается здесь не дальше предела и передаётся приложению повтором.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope['type'] != 'http' or scope.get('method') not in ('POST', 'PUT', 'PATCH'):
            await self.app(scope, receive, send)
            return
        limit = body_limit_bytes()
        length = next((v for k, v in scope.get('headers', []) if k == b'content-length'), None)
        if length is not None:
            if not length.isdigit() or int(length) > limit:
                await _reject(send, limit)
                return
            await self.app(scope, receive, send)
            return
        messages, received = [], 0
        while True:
            msg = await receive()
            messages.append(msg)
            if msg['type'] != 'http.request':
                break
            received += len(msg.get('body', b''))
            if received > limit:
                await _reject(send, limit)
                return
            if not msg.get('more_body'):
                break
        replay = iter(messages)

        async def replay_receive() -> dict:
            return next(replay, None) or await receive()

        await self.app(scope, replay_receive, send)


async def _reject(send: Any, limit: int) -> None:
    body = json.dumps({'code': PayloadTooLarge.code, 'message_ru': f'Тело запроса больше {limit // _CHUNK} МБ', 'details': {}}, ensure_ascii=False).encode()
    await send({'type': 'http.response.start', 'status': 413, 'headers': [(b'content-type', b'application/json; charset=utf-8'), (b'content-length', str(len(body)).encode())]})
    await send({'type': 'http.response.body', 'body': body})
