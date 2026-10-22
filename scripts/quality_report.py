#!/usr/bin/env python3
"""Регенерирует `docs/reports/quality.md` фактическими числами локальной проверки (MET-8, F17).

Запуск из корня: `python scripts/quality_report.py`
Раздел 1 (живой замер на Cloud.ru) не пересчитывается локально — он переносится
из предыдущей версии отчёта и обновляется только точечным живым прогоном на стенде.

SPEC-Q-01 (MET-57/R13): провал обязательной проверки виден и в отчёте, и в коде выхода.
Наличие строк «done» или отсутствие латинского FAIL в выводе — не успех: учитываются
код возврата дочернего процесса и его сводка («N failed», «N error», «чек-лист X/Y»).
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'docs' / 'reports' / 'quality.md'
ENV = {**__import__('os').environ, 'PYTHONPATH': str(ROOT / 'src'), 'LLM_PROVIDERS': 'fixtures'}


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=ENV, check=False)
    return r.returncode, r.stdout + r.stderr


def _pytest_verdict(rc: int, out: str) -> dict[str, Any]:
    """PASS только при коде 0 и без «N failed»/«N error» в сводке pytest (SPEC-Q-01)."""

    def num(pat: str) -> int:
        m = re.search(pat, out)
        return int(m.group(1)) if m else 0

    failed, errors = num(r'(\d+) failed'), num(r'(\d+) error')
    passed, skipped = re.search(r'(\d+) passed', out), re.search(r'(\d+) skipped', out)
    cov = re.search(r'Total coverage: (\d+[.,]\d+)%', out)
    summary = f'{passed.group(1) if passed else "?"} passed, {skipped.group(1) if skipped else "0"} skipped'
    if failed or errors:
        summary += f', {failed} failed, {errors} error'
    ok = rc == 0 and failed == 0 and errors == 0
    return {'status': 'PASS' if ok else 'FAIL', 'text': summary, 'failed': failed, 'errors': errors,
            'coverage': (cov.group(1) if cov else '?').replace(',', '.')}


def _pytest() -> dict[str, Any]:
    rc, out = _run([sys.executable, '-m', 'pytest', '-q', '--cov=src/app', '--cov-report=term'])
    return _pytest_verdict(rc, out)


def _autorun_verdict(rc: int, out: str) -> dict[str, Any]:
    """PASS только при коде 0 и финальном маркере autorun «все кейсы и выгрузки прошли» (SPEC-Q-01)."""
    pairs = re.findall(r'чек-лист (\d+)/(\d+)', out)
    lists = f'чек-листы {sum(int(a) for a, _ in pairs)}/{sum(int(b) for _, b in pairs)}' if pairs else 'чек-листы —'
    if rc == 0 and 'все кейсы и выгрузки прошли' in out:
        return {'status': 'PASS', 'text': f'5/5 done, {lists}'}
    return {'status': 'FAIL', 'text': f'ПРОВАЛ — код {rc}, {lists}; см. logs/autorun/'}


def _autorun() -> dict[str, Any]:
    rc, out = _run([sys.executable, 'scripts/autorun.py'], timeout=900)
    return _autorun_verdict(rc, out)


def _trace() -> str:
    rc, out = _run([sys.executable, 'scripts/spec_trace.py'])
    m = re.search(r'ИТОГО: требований (\d+), покрыто тестами (\d+)', out)
    return f'{m.group(2)}/{m.group(1)}' if m else f'— (код {rc})'


def _constraints() -> str:
    rc, out = _run([sys.executable, 'scripts/check_constraints.py'])
    return 'соблюдены' if rc == 0 and 'соблюдены' in out else f'НАРУШЕНЫ (код {rc})'


def build_report_data() -> dict[str, Any]:
    """Собирает фактические результаты проверок; ok — прошли все обязательные (SPEC-Q-01).

    Обязательные проверки — `pytest` и автопрогон; трассировка и ограничения кейса
    в отчёте информационные и на код выхода не влияют.
    """
    tests, autor = _pytest(), _autorun()
    return {'pytest': tests, 'autorun': autor, 'trace': _trace(), 'constraints': _constraints(),
            'ok': tests['status'] == 'PASS' and autor['status'] == 'PASS'}


def main() -> int:
    old = REPORT.read_text(encoding='utf-8') if REPORT.exists() else ''
    live = ''
    if old:
        m = re.search(r'## 1\. Живой прогон.*?(?=## 2\. )', old, flags=re.DOTALL)
        if m:
            live = m.group(0)
    data = build_report_data()
    tests, autor = data['pytest'], data['autorun']
    run = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
    sha = ''
    try:
        sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:  # noqa: BLE001 — вне git-копии отчёт всё равно строится
        pass
    if not live:
        live = ('## 1. Живой прогон на реальной модели (не fixtures)\n\n'
                'Раздел заполняется точечным живым прогоном на стенде (последний: 21.10.2026 — см. историю git).\n\n')
    verdict = 'ЕСТЬ ПРОВАЛЫ' if not data['ok'] else 'обязательные проверки пройдены'
    body = f'''# Отчёт качества и воспроизводимости

Обновляется командой `python scripts/quality_report.py`; последний прогон: **{run}**, коммит `{sha or '—'}`.
Итог обязательных проверок (`pytest`, автопрогон): **{verdict}**.

{live}## 2. Регресс на детерминированных ответах (fixtures)

| Проверка | Статус | Результат |
|---|---|---|
| `pytest` (тестов) | **{tests['status']}** | **{tests['text']}** |
| Покрытие `src/app` | — | **{tests['coverage']} %** (порог 70 %) |
| Автопрогон 5 открытых кейсов (`scripts/autorun.py`) | **{autor['status']}** | {autor['text']} |
| Трассировка SDD | — | {data['trace']} в автотестах; SPEC-UI — vitest + браузерный прогон |
| Ограничения кейса (`scripts/check_constraints.py`) | — | {data['constraints']} |

## 3. Как воспроизвести

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock
cd frontend && npm ci && npm run build && cd ..
make check                                   # весь конвейер одной командой
LLM_PROVIDERS=fixtures DATA_DIR=$(mktemp -d) PYTHONPATH=src python -m uvicorn app.main:app --port 8765 &
python scripts/autorun.py                    # 5 кейсов, exit 0 только при полном PASS
python scripts/e2e_regression.py --base http://127.0.0.1:8765 --all-cases
BASE_URL=http://127.0.0.1:8765 NODE_PATH=$(npm root -g) node e2e/ui_roles.spec.cjs
```

## 4. Допущения

- Раздел 1 — точечный живой прогон на стенде; повторяемость подтверждается ежедневными автопрогонами организаторов и разделом 2 на фикстурах.
- Оценка эффекта методиста — расчёт по нормам, подписан как расчёт; фактический замер ручной доработки — план пилота.
'''
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(body, encoding='utf-8')
    print(f'docs/reports/quality.md обновлён: {tests["text"]}, покрытие {tests["coverage"]} %')
    if not data['ok']:
        print('ОТЧЁТ: ЕСТЬ ПРОВАЛЫ — обязательные проверки не пройдены, статусы FAIL в docs/reports/quality.md')
        return 1
    print('Отчёт: обязательные проверки пройдены')
    return 0


if __name__ == '__main__':
    sys.exit(main())
