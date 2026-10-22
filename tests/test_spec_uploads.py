"""Спецификация api.md: приём вложений — размер и тип до декодирования и чтения в память (прогон 22.10)."""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

ROOT = Path(__file__).resolve().parents[1]
DOCX = (ROOT / 'data' / 'samples' / 'doop_intensiv_ai_24.docx').read_bytes()
REQ = 'Общеразвивающая программа «Первые шаги в Python» для школьников 8–9 классов, 16 часов, очно.'


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.kb.registry import registry

    registry.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


def _att(name: str, content: bytes) -> dict[str, str]:
    return {'name': name, 'content_base64': base64.b64encode(content).decode()}


def test_body_limit_rejects_before_parsing(client, monkeypatch) -> None:
    """SPEC-API-41"""
    from app.core.config import get_settings
    from app.core.uploads import BodyLimit, body_limit_bytes

    monkeypatch.setattr(get_settings(), 'max_file_size_mb', 0)  # предел тела — 1 МБ запаса
    big = b'{"request": "' + b'x' * (body_limit_bytes() + 10) + b'"}'
    r = client.post('/api/v1/programs', content=big, headers={**_h(client, 'u-madina'), 'content-type': 'application/json'})
    assert r.status_code == 413 and r.json()['code'] == 'PAYLOAD_TOO_LARGE'

    # Тело без Content-Length (chunked): дочитывается не дальше предела, приложение не вызывается
    called = []

    async def app(scope, receive, send):
        called.append(await receive())

    chunks = [{'type': 'http.request', 'body': b'x' * 600_000, 'more_body': True} for _ in range(3)]
    sent = []

    async def receive():
        return chunks.pop(0)

    async def send(msg):
        sent.append(msg)

    asyncio.run(BodyLimit(app)({'type': 'http', 'method': 'POST', 'headers': []}, receive, send))
    assert sent[0]['status'] == 413 and not called

    # В пределе тело передаётся приложению без потерь
    small = [{'type': 'http.request', 'body': b'ab', 'more_body': True}, {'type': 'http.request', 'body': b'c', 'more_body': False}]

    async def receive_small():
        return small.pop(0)

    got = []

    async def app2(scope, receive, send):
        got.extend([(await receive())['body'], (await receive())['body']])

    asyncio.run(BodyLimit(app2)({'type': 'http', 'method': 'POST', 'headers': []}, receive_small, send))
    assert got == [b'ab', b'c']


def test_multipart_uploads_limited_on_every_path(client, monkeypatch) -> None:
    """SPEC-API-42"""
    from app.core.config import get_settings

    hm, ha = _h(client, 'u-madina'), _h(client, 'u-admin')
    monkeypatch.setattr(get_settings(), 'max_file_size_mb', 1)
    big = ('big.docx', b'PK\x03\x04' + b'0' * (1024 * 1024 + 10))
    cases = [
        ('/api/v1/programs/upload', hm, {'text': REQ}, 'files'),
        ('/api/v1/actualize', hm, {}, 'file'),
        ('/api/v1/kb/documents', ha, {'kind': 'other'}, 'file'),
    ]
    for url, h, data, field in cases:
        r = client.post(url, data=data, files={field: big}, headers=h)
        assert r.status_code == 413, (url, r.text)
        assert r.json()['code'] == 'PAYLOAD_TOO_LARGE' and 'больше 1 МБ' in r.json()['message_ru']
    many = [('files', (f'f{i}.txt', b'hello')) for i in range(get_settings().max_files_per_request + 1)]
    r = client.post('/api/v1/programs/upload', data={'text': REQ}, files=many, headers=hm)
    assert r.status_code == 400 and 'файлов' in r.json()['message_ru']


def test_type_whitelist_and_signature_match(client) -> None:
    """SPEC-API-43"""
    hm, ha = _h(client, 'u-madina'), _h(client, 'u-admin')
    bad = [('a.exe', DOCX), ('x.pdf', b'<html><script>alert(1)</script></html>'), ('p.docx', b'%PDF-1.7 fake')]
    for name, content in bad:
        r = client.post('/api/v1/programs', json={'request': REQ, 'attachments': [_att(name, content)]}, headers=hm)
        assert r.status_code == 415 and r.json()['code'] == 'UNSUPPORTED_MEDIA_TYPE', (name, r.text)
    for url, h, field in [('/api/v1/actualize', hm, 'file'), ('/api/v1/kb/documents', ha, 'file')]:
        r = client.post(url, files={field: ('a.exe', DOCX)}, headers=h)
        assert r.status_code == 415, (url, r.text)
    r = client.post('/api/v1/programs/upload', data={'text': REQ}, files={'files': ('virus.bat', b'echo')}, headers=hm)
    assert r.status_code == 415
    r = client.post('/api/v1/actualize', files={'file': ('empty.txt', b'')}, headers=hm)
    assert r.status_code == 400 and 'пустой' in r.json()['message_ru']
    # файл без расширения принимается по сигнатуре; верные .docx и .md — тоже
    for name, content in [('Программа АЦР', DOCX), ('ref.docx', DOCX), ('notes.md', '# Темы\nPython'.encode())]:
        r = client.post('/api/v1/actualize', files={'file': (name, content)}, headers=hm)
        assert r.status_code == 200, (name, r.text)


def test_base64_line_breaks_and_data_prefix_accepted(client) -> None:
    """SPEC-API-44"""
    from app.core.uploads import decode_base64

    raw = 'Темы: pandas, SQL, визуализация.'.encode() * 20
    wrapped = base64.encodebytes(raw).decode()  # переносы по 76 символов
    assert '\n' in wrapped and decode_base64('a.txt', wrapped) == raw
    assert decode_base64('a.txt', 'data:text/plain;base64,' + base64.b64encode(raw).decode()) == raw
    r = client.post('/api/v1/programs', json={'request': REQ, 'attachments': [{'name': 'ref.txt', 'content_base64': wrapped}]}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
