"""Трассировка SDD: тесты ссылаются только на требования, объявленные в specs/*.md (specs/README.md)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'spec_trace.py'


def _load():
    import importlib.util

    spec = importlib.util.spec_from_file_location('spec_trace', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['spec_trace'] = mod
    spec.loader.exec_module(mod)
    return mod


def test_no_unknown_requirement_ids() -> None:
    st = _load()
    trace = st.collect(ROOT)
    assert trace.requirements, 'в specs/*.md нет таблиц требований'
    assert not trace.unknown, f'тесты ссылаются на неизвестные ID: {trace.unknown}'
    assert not trace.duplicates, f'ID объявлены повторно: {trace.duplicates}'


def test_script_exits_zero_and_prints_summary() -> None:
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'auth-and-roles.md: требований' in r.stdout and 'ИТОГО' in r.stdout


def test_unknown_id_fails(tmp_path) -> None:
    (tmp_path / 'specs').mkdir()
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'specs' / 'x.md').write_text('| ID | Требование | Источник | Тест |\n|---|---|---|---|\n| SPEC-X-01 | THE SYSTEM SHALL … | код | — |\n', encoding='utf-8')
    (tmp_path / 'tests' / 'test_x.py').write_text('def test_a():\n    """SPEC-X-01, SPEC-X-02"""\n', encoding='utf-8')
    st = _load()
    trace = st.collect(tmp_path)
    assert trace.covered('x.md') == ['SPEC-X-01'] and list(trace.unknown) == ['SPEC-X-02']
    assert st.main(['--root', str(tmp_path)]) == 1
