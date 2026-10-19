"""Демонстрация двух свойств основного сценария на запущенном сервисе (только стандартная библиотека):

1. Шаг уточнения встроен в конвейер: на неполный запрос сервис отвечает вопросами (needs_answers),
   ответы через API продолжают тот же конвейер до полного комплекта.
2. Слайды собираются без модели: при LLM_PROVIDERS=fixtures (или отказе шлюза) выгрузка PPTX
   содержит слайды хотя бы одного модуля.

    LLM_PROVIDERS=fixtures PYTHONPATH=src uvicorn app.main:app --port 8000 &
    python scripts/demo_clarify_slides.py --base http://127.0.0.1:8000

Код выхода 0 — оба свойства подтверждены.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile

REQUEST = 'Нужен курс по Excel для бухгалтеров'  # нет типа программы, объёма и итоговой аттестации


def call(base: str, path: str, body: dict | None = None, token: str = '') -> tuple[int, bytes]:
    req = urllib.request.Request(base + path, method='POST' if body is not None else 'GET',
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json', **({'X-MA-Token': token} if token else {})})
    with urllib.request.urlopen(req, timeout=900) as r:
        return r.status, r.read()


def check(ok: bool, msg: str) -> None:
    print(('OK   ' if ok else 'FAIL ') + msg)
    if not ok:
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    base = ap.parse_args().base.rstrip('/')

    _, raw = call(base, '/api/v1/auth/login', {'login': 'api', 'password': 'demo'})
    token = json.loads(raw)['access_token']

    print(f'1) Неполный запрос: «{REQUEST}»')
    _, raw = call(base, '/api/v1/programs', {'request': REQUEST}, token)
    j = json.loads(raw)
    check(j.get('status') == 'questions' and j.get('needs_answers') is True, 'конвейер остановился на шаге clarify и вернул вопросы')
    for q in j['questions']:
        print(f'     ? {q["text"]}  [{" / ".join(map(str, q.get("options", [])[:4]))}]')
    fields = {q['field'] for q in j['questions']}
    check({'program_type', 'volume_h'} <= fields, 'спрошены тип программы и объём')

    answers = {'program_type': 'Повышение квалификации', 'volume_h': '36'}
    print(f'2) Ответы через API: {answers}')
    _, raw = call(base, f'/api/v1/programs/{j["program_id"]}/answers?mode=auto', {'answers': answers}, token)
    k = json.loads(raw)
    check(k['status'] in ('done', 'done_with_errors'), f'тот же конвейер дошёл до комплекта: status {k["status"]}')
    check(k['skeleton']['totals']['all'] == 36, 'объём из ответа учтён: 36 ч')
    asked = {q['field']: q.get('answer') for q in k['questions_asked']}
    check(asked.get('volume_h') == '36', 'ответы записаны в questions_asked')
    print(f'     допущения по остальным полям: {", ".join(a["field"] for a in k["assumptions"]) or "нет"}')

    print('3) Слайды в выгрузке PPTX')
    _, pptx = call(base, re.sub(r'^https?://[^/]+', '', k['files']['pptx']), token=token)
    slides = [n for n in zipfile.ZipFile(io.BytesIO(pptx)).namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)]
    check(len(slides) >= 4, f'в PPTX {len(slides)} слайдов')
    _, raw = call(base, '/api/v1/llm/status', token=token)
    llm = json.loads(raw)
    print(f'     модель: {"подключена" if llm.get("ok") else "не используется — слайды собраны без LLM"}')
    print(f'     отказы навыков (step_errors): {len(k.get("step_errors", []))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
