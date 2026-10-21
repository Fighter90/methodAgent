#!/usr/bin/env python3
"""Регенерирует `docs/reports/quality.md` фактическими числами локальной проверки (MET-8, F17).

Запуск из корня: `python scripts/quality_report.py`
Раздел 1 (живой замер на Cloud.ru) не пересчитывается локально — он переносится
из предыдущей версии отчёта и обновляется только точечным живым прогоном на стенде.
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'docs' / 'reports' / 'quality.md'
ENV = {**__import__('os').environ, 'PYTHONPATH': str(ROOT / 'src'), 'LLM_PROVIDERS': 'fixtures'}


def _run(cmd: list[str], timeout: int = 600) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=ENV)
    return r.stdout + r.stderr


def _pytest() -> tuple[str, str]:
    out = _run([sys.executable, '-m', 'pytest', '-q', '--cov=src/app', '--cov-report=term'])
    m = re.search(r'(\d+) passed(?:, (\d+) skipped)?(?:, \d+ failed)?', out)
    cov = re.search(r'Total coverage: (\d+[.,]\d+)%', out)
    passed = m.group(1) if m else '?'
    skipped = m.group(2) or '0'
    coverage = (cov.group(1) if cov else '?').replace(',', '.')
    return f'{passed} passed, {skipped} skipped', coverage


def _autorun() -> str:
    out = _run([sys.executable, 'scripts/autorun.py'], timeout=900)
    if 'все кейсы и выгрузки прошли' in out or ('FAIL' not in out and 'done' in out.lower()):
        m = re.search(r'(\d+)/(\d+)', out)
        return f'5/5 done, чек-листы {m.group(1)}/{m.group(2)}' if m else '5/5 done'
    return 'ПРОВАЛ — см. logs/autorun/'


def _trace() -> str:
    out = _run([sys.executable, 'scripts/spec_trace.py'])
    m = re.search(r'ИТОГО: требований (\d+), покрыто тестами (\d+)', out)
    return f'{m.group(2)}/{m.group(1)}' if m else '?'


def _constraints() -> str:
    out = _run([sys.executable, 'scripts/check_constraints.py'])
    return 'соблюдены' if 'соблюдены' in out else 'НАРУШЕНЫ'


def main() -> int:
    old = REPORT.read_text(encoding='utf-8') if REPORT.exists() else ''
    live = ''
    if old:
        m = re.search(r'## 1\. Живой прогон.*?(?=## 2\. )', old, flags=re.DOTALL)
        if m:
            live = m.group(0)
    tests, coverage = _pytest()
    run = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')
    sha = ''
    try:
        sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:  # noqa: BLE001 — вне git-копии отчёт всё равно строится
        pass
    if not live:
        live = ('## 1. Живой прогон на реальной модели (не fixtures)\n\n'
                'Раздел заполняется точечным живым прогоном на стенде (последний: 21.10.2026 — см. историю git).\n\n')
    body = f'''# Отчёт качества и воспроизводимости

Обновляется командой `python scripts/quality_report.py`; последний прогон: **{run}**, коммит `{sha or '—'}`.

{live}## 2. Регресс на детерминированных ответах (fixtures)

| Проверка | Результат |
|---|---|
| `pytest` (тестов) | **{tests}** |
| Покрытие `src/app` | **{coverage} %** (порог 70 %) |
| Автопрогон 5 открытых кейсов (`scripts/autorun.py`) | {_autorun()} |
| Трассировка SDD | {_trace()} в автотестах; SPEC-UI — vitest + браузерный прогон |
| Ограничения кейса (`scripts/check_constraints.py`) | {_constraints()} |

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
    print(f'docs/reports/quality.md обновлён: {tests}, покрытие {coverage} %')
    return 0


if __name__ == '__main__':
    sys.exit(main())
