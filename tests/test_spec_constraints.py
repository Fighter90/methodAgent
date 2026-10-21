"""Спецификация specs/api.md: автоматический контроль ограничений кейса (MET-12, F19)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

ROOT = Path(__file__).resolve().parents[1]


def test_constraints_check_passes() -> None:
    """SPEC-API-33"""
    r = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'check_constraints.py')],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
        env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
    )
    assert r.returncode == 0, f'ограничения кейса нарушены:\n{r.stdout}\n{r.stderr}'
    assert 'соблюдены' in r.stdout
