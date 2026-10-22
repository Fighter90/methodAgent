"""Отчёт качества (specs/quality.md): провал обязательной проверки виден в статусах и коде выхода."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load_report() -> Any:
    """Загружает scripts/quality_report.py как модуль (проверки при импорте не запускаются)."""
    spec = importlib.util.spec_from_file_location('quality_report_under_test', ROOT / 'scripts' / 'quality_report.py')
    mod: Any = importlib.util.module_from_spec(spec)
    sys.modules['quality_report_under_test'] = mod
    spec.loader.exec_module(mod)
    return mod


qr = _load_report()

FAIL_PYTEST = {'status': 'FAIL', 'text': '2 failed, 366 passed', 'failed': 2, 'errors': 0, 'coverage': '91.80'}
OK_PYTEST = {'status': 'PASS', 'text': '368 passed, 1 skipped', 'failed': 0, 'errors': 0, 'coverage': '91.80'}
OK_AUTORUN = {'status': 'PASS', 'text': '5/5 done, чек-листы 55/56'}
FAIL_AUTORUN = {'status': 'FAIL', 'text': 'ПРОВАЛ — код 1, чек-листы 54/56; см. logs/autorun/'}


def _patch(monkeypatch: Any, tests: dict[str, Any], autorun: dict[str, Any]) -> None:
    """Подменяет дочерние проверки: сбор отчёта не должен запускать pytest и autorun по-настоящему."""
    monkeypatch.setattr(qr, '_pytest', lambda: tests)
    monkeypatch.setattr(qr, '_autorun', lambda: autorun)
    monkeypatch.setattr(qr, '_trace', lambda: '311/311')
    monkeypatch.setattr(qr, '_constraints', lambda: 'соблюдены')


def test_build_report_data_marks_failures(monkeypatch: Any) -> None:
    """SPEC-Q-01: провал pytest или автопрогона даёт статус FAIL и общий итог «есть провал»."""
    _patch(monkeypatch, FAIL_PYTEST, OK_AUTORUN)
    data = qr.build_report_data()
    assert data['pytest']['status'] == 'FAIL' and data['autorun']['status'] == 'PASS'
    assert data['ok'] is False

    _patch(monkeypatch, OK_PYTEST, FAIL_AUTORUN)
    data = qr.build_report_data()
    assert data['pytest']['status'] == 'PASS' and data['autorun']['status'] == 'FAIL'
    assert data['ok'] is False


def test_build_report_data_happy_path(monkeypatch: Any) -> None:
    """SPEC-Q-01: зелёные обязательные проверки — статусы PASS и ok=True."""
    _patch(monkeypatch, OK_PYTEST, OK_AUTORUN)
    data = qr.build_report_data()
    assert data['ok'] is True
    assert data['pytest']['status'] == 'PASS' and data['autorun']['status'] == 'PASS'


def test_pytest_verdict_reads_failures() -> None:
    """SPEC-Q-01: «2 failed» или «E errors» в выводе pytest дают FAIL, сколько бы ни было passed."""
    v = qr._pytest_verdict(0, '2 failed, 366 passed, 1 skipped in 42.13s')
    assert v['status'] == 'FAIL' and v['failed'] == 2 and '366 passed' in v['text']
    v = qr._pytest_verdict(0, '366 passed, 1 error in 42.13s')
    assert v['status'] == 'FAIL' and v['errors'] == 1
    v = qr._pytest_verdict(1, '366 passed in 42.13s')  # ненулевой код (например, покрытие ниже порога)
    assert v['status'] == 'FAIL'
    v = qr._pytest_verdict(0, '366 passed, 1 skipped in 42.13s\nTotal coverage: 91.80%')
    assert v['status'] == 'PASS' and v['coverage'] == '91.80'


def test_autorun_verdict_reads_markers() -> None:
    """SPEC-Q-01: статус autorun решают код возврата и финальный маркер, «наличие done» — не успех."""
    v = qr._autorun_verdict(1, 'Запрос 3: done_with_errors, проверки 9/10, чек-лист 9/10\nАвтопрогон провален:')
    assert v['status'] == 'FAIL' and '9/10' in v['text']
    v = qr._autorun_verdict(0, 'Запрос 1: done, проверки 10/10, чек-лист 11/11\nАвтопрогон: все кейсы и выгрузки прошли')
    assert v['status'] == 'PASS' and '11/11' in v['text']
    v = qr._autorun_verdict(0, 'Запрос 1: done, done — финального маркера нет')
    assert v['status'] == 'FAIL'


def test_main_exit_code_and_report(tmp_path: Path, monkeypatch: Any) -> None:
    """SPEC-Q-01: провал — main() пишет FAIL в отчёт и возвращает 1; успех — PASS и 0."""
    report = tmp_path / 'quality.md'
    monkeypatch.setattr(qr, 'REPORT', report)
    _patch(monkeypatch, FAIL_PYTEST, OK_AUTORUN)
    assert qr.main() == 1
    text = report.read_text(encoding='utf-8')
    assert 'ЕСТЬ ПРОВАЛЫ' in text and '**FAIL**' in text

    _patch(monkeypatch, OK_PYTEST, OK_AUTORUN)
    assert qr.main() == 0
    text = report.read_text(encoding='utf-8')
    assert 'обязательные проверки пройдены' in text and '**PASS**' in text and 'FAIL' not in text
