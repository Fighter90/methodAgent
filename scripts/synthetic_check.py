#!/usr/bin/env python3
"""Проба 10 синтетических объёмов (ТЗ 6.1, MET-8/F17): 16…500 ч через POST /programs?mode=auto на fixtures.

Проверяет для каждого объёма: статус done, блокирующие 10/10, сходимость суммы с запрошенной,
замеряет время. Результат дописывается в docs/reports/quality.md (секция «Синтетические объёмы»).
Запуск: python scripts/synthetic_check.py
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ.setdefault('LLM_PROVIDERS', 'fixtures')
_TMP_DATA = tempfile.mkdtemp()  # удаляется в конце main()
os.environ.setdefault('DATA_DIR', _TMP_DATA)

# (объём, фраза типа, направление) — оба шаблона, 2 стажировки, разные направления (ТЗ 6.1)
CASES = [
    (16, 'дополнительную общеразвивающую программу', 'Первые шаги в Python'),
    (24, 'дополнительную общеразвивающую программу', 'Дизайн интерфейсов для начинающих'),
    (36, 'программу повышения квалификации', 'ИИ в работе учителя'),
    (48, 'программу повышения квалификации', 'Современная веб-разработка'),
    (72, 'программу повышения квалификации', 'Анализ данных на Python'),
    (108, 'программу повышения квалификации', 'Тестирование программного обеспечения'),
    (144, 'программу повышения квалификации в форме стажировки', 'DevOps-инженер от Linux до CI/CD'),
    (256, 'дополнительную общеразвивающую программу', 'Основы алгоритмики'),
    (360, 'программу повышения квалификации', 'Кибербезопасность для организаций'),
    (500, 'программу повышения квалификации в форме стажировки', 'Бизнес и системный анализ'),
]

# Обращение идёт к ПУБЛИЧНОМУ API-эндпоинту своего приложения (требование «единый эндпоинт»),
# поэтому llm/gateway.py здесь не участвует — все вызовы модели внутри приложения идут через него.
# Демо-учётка fixtures-режима публична (как во всех скриптах репозитория), переопределяется окружением.


def _probe(client) -> tuple[list[str], list[str]]:
    """Прогоняет 10 объёмов; возвращает строки таблицы и список провалов."""
    login = os.environ.get('DEMO_LOGIN', 'madina')
    password = os.environ.get('DEMO_PASSWORD', 'demo')
    auth = client.post('/api/v1/auth/login', json={'login': login, 'password': password})
    if auth.status_code != 200:
        return [f'аутентификация демо-учётки не прошла: HTTP {auth.status_code}'], [f'login HTTP {auth.status_code}']
    head = {'X-MA-Token': auth.json()['access_token']}
    rows: list[str] = []
    fails: list[str] = []
    for vol, kind, title in CASES:
        extra = ', вся работа самостоятельная, аудиторных занятий нет, итоговая аттестация 2 часа в форме защиты отчёта' \
            if 'стажировк' in kind else ', итоговая аттестация в виде защиты проекта'
        request = f'Нужна {kind} на {vol} часов «{title}» для специалистов, очно-заочная форма{extra}.'
        t0 = time.monotonic()
        r = client.post('/api/v1/programs?mode=auto', json={'request': request, 'wait': True}, headers=head)
        dt = time.monotonic() - t0
        if r.status_code not in (200, 202):
            fails.append(f'{vol} ч: HTTP {r.status_code}')
            rows.append(f'| {vol} | — | — | — | {dt:.0f} |')
            continue
        d = r.json()
        blocking = d.get('report', {}).get('blocking_checks', '?')
        totals = (d.get('skeleton') or {}).get('totals', {})
        total_h = totals.get('all') if 'all' in totals else totals.get('total')
        if d.get('status') != 'done' or blocking != '10/10' or total_h != vol:
            fails.append(f'{vol} ч: статус {d.get("status")}, проверки {blocking}, сумма {total_h}')
        rows.append(f'| {vol} | {d.get("status", "?")} | {blocking} | {total_h} | {dt:.0f} |')
        print(f'{vol:>3} ч: {d.get("status"):16} 10/10={blocking} сумма={total_h} {dt:.0f} с', flush=True)
    return rows, fails


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import create_app

    rows: list[str] = []
    fails: list[str] = []
    try:
        with TestClient(create_app()) as client:  # with: запускает lifespan → init_db создаёт таблицы
            rows, fails = _probe(client)
    finally:
        shutil.rmtree(_TMP_DATA, ignore_errors=True)
    table = '\n'.join(['| Объём, ч | Статус | Блокирующие | Сумма, ч | Время, с |', '|---|---|---|---|---|', *rows])
    note = f'**Провалы:** {"; ".join(fails)}\n\n' if fails else 'Все объёмы собраны корректно, суммы сходятся.\n\n'
    section = ('### Синтетические объёмы 16–500 ч (fixtures, ТЗ 6.1)\n\n'
               f'Прогон {datetime.date.today().strftime("%d.%m.%Y")}: 10 запросов одним эндпоинтом, детерминированный режим.\n\n'
               f'{table}\n\n{note}')
    rep = ROOT / 'docs' / 'reports' / 'quality.md'
    text = rep.read_text(encoding='utf-8') if rep.exists() else ''
    text = re.sub(r'### Синтетические объёмы 16–500 ч.*?(?=## 3\. )', section, text, flags=re.DOTALL, count=1)
    if 'Синтетические объёмы' not in text:
        text = text.replace('## 3. Как воспроизвести', section + '## 3. Как воспроизвести')
    rep.write_text(text, encoding='utf-8')
    if fails:
        print('ЕСТЬ ПРОВАЛЫ — см. таблицу в docs/reports/quality.md')
        return 1
    print('СИНТЕТИЧЕСКАЯ ПРОБА: 10/10 PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
