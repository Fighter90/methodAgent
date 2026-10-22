"""Спецификация specs/validation-sandbox.md: песочница примеров кода (V-24, FR-46)."""

from __future__ import annotations

import os
import resource
import subprocess
import sys

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.core.config import get_settings  # noqa: E402
from app.programs.schemas import Lecture, ProgramDoc  # noqa: E402
from app.validation import sandbox  # noqa: E402


@pytest.fixture(scope='module')
def runtime() -> None:
    probe = sandbox.run_detailed('print(1)')
    if not probe['ok'] or probe['stdout'].strip() != '1':
        pytest.skip(f'Песочница недоступна: {probe["error"]}')


def test_empty_code_skipped() -> None:
    """SPEC-SANDBOX-01: пустой пример не запускается: ok, режим skip."""
    r = sandbox.run_detailed('   \n')
    assert r['ok'] and r['mode'] == 'skip' and r['error'] == ''


@pytest.mark.parametrize('code', [
    'import os\nprint(os.getcwd())',
    'open("x.txt")',
    'print(__import__("sys"))',
    'eval("1+1")',
    'import socket',
    'import io\nprint(io.DEFAULT_BUFFER_SIZE)',
    'from io import StringIO',
    'import runpy\nprint(runpy)',
    'import code\nprint(code)',
    'import operator\nprint(operator.add(1, 2))',
])
def test_system_access_not_run(code: str, monkeypatch) -> None:
    """SPEC-SANDBOX-02: пример, обращающийся к системе, сети, файлам, dunder-атрибутам, eval или модулям io/runpy/code/operator (аудит 19.10), не запускается и помечается для ручной проверки."""
    monkeypatch.setattr(sandbox.subprocess, 'run', lambda *a, **k: pytest.fail('не должен запускаться'))
    r = sandbox.run_detailed(code)
    assert r['mode'] == 'skip' and r['ok'] and 'проверьте вручную' in r['error']


def test_heavy_libraries_syntax_only(monkeypatch) -> None:
    """SPEC-SANDBOX-03: пример с тяжёлыми библиотеками или sqlite3 проверяется только на синтаксис, без запуска процесса."""
    monkeypatch.setattr(sandbox.subprocess, 'run', lambda *a, **k: pytest.fail('не должен запускаться'))
    ok = sandbox.run_detailed('import pandas as pd\ndf = pd.DataFrame()\n')
    assert ok['ok'] and ok['mode'] == 'syntax'
    bad = sandbox.run_detailed('import numpy as np\nx = np.array([1, 2\n')
    assert not bad['ok'] and bad['mode'] == 'syntax' and bad['error'].startswith('Синтаксическая ошибка')
    assert 'строка' in bad['error']
    assert sandbox.run_detailed('import sqlite3\nc = sqlite3.connect(":memory:")')['mode'] == 'syntax'


def test_libraries_detected_in_order() -> None:
    """SPEC-SANDBOX-04: libraries возвращает импортируемые библиотеки без повторов в порядке появления."""
    code = 'import pandas as pd\nfrom math import pi\n  import pandas\nimport json\n'
    assert sandbox.libraries(code) == ['pandas', 'math', 'json']


def test_run_success_stdout_and_input(runtime) -> None:
    """SPEC-SANDBOX-05: корректный пример выполняется в отдельном процессе; возвращаются stdout, время и режим run; input() получает данные."""
    r = sandbox.run_detailed('a = int(input())\nprint(a * 2)')
    assert r['ok'] and r['mode'] == 'run' and r['stdout'].strip() == '10'
    assert r['seconds'] >= 0


def test_run_error_last_stderr_line(runtime) -> None:
    """SPEC-SANDBOX-06: при ошибке выполнения ok=False, текст ошибки — последняя строка stderr."""
    r = sandbox.run_detailed('print("до")\nraise ValueError("плохо")')
    assert not r['ok'] and r['error'] == 'ValueError: плохо' and 'до' in r['stdout']


def test_network_is_blocked(runtime, monkeypatch) -> None:
    """SPEC-SANDBOX-07: дочерний процесс запускается с пустым прокси и изолированным окружением (без переменных родителя)."""
    captured = {}
    real = subprocess.run

    def spy(cmd, **kw):
        captured.update(kw)
        return real(cmd, **kw)

    monkeypatch.setattr(sandbox.subprocess, 'run', spy)
    assert sandbox.run_detailed('print(1)')['ok']
    assert captured['env']['HTTPS_PROXY'] == 'http://0.0.0.0:9' and 'DATA_DIR' not in captured['env']
    assert captured['timeout'] == get_settings().sandbox_timeout_s == 10


def test_limits_from_settings(monkeypatch) -> None:
    """SPEC-SANDBOX-11: лимиты времени и памяти песочницы берутся из SANDBOX_TIMEOUT_S и SANDBOX_MEMORY_MB (по умолчанию 10 с и 512 МБ)."""
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert (s.sandbox_timeout_s, s.sandbox_memory_mb) == (10, 512)
    monkeypatch.setenv('SANDBOX_TIMEOUT_S', '3')
    monkeypatch.setenv('SANDBOX_MEMORY_MB', '256')
    s = Settings(_env_file=None)
    assert (s.sandbox_timeout_s, s.sandbox_memory_mb) == (3, 256)
    captured = {}

    def fake(cmd, **kw):
        captured.update(kw)
        raise subprocess.TimeoutExpired(cmd='python', timeout=3)

    monkeypatch.setattr(sandbox, 'get_settings', lambda: s)
    monkeypatch.setattr(sandbox.subprocess, 'run', fake)
    r = sandbox.run_detailed('print(1)')
    assert captured['timeout'] == 3 and r['error'] == 'Пример выполняется дольше 3 с' and r['seconds'] == 3.0


def test_timeout_reported(monkeypatch) -> None:
    """SPEC-SANDBOX-08: IF пример выполняется дольше лимита, THEN ok=False с сообщением о 10 с."""
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd='python', timeout=10)

    monkeypatch.setattr(sandbox.subprocess, 'run', boom)
    r = sandbox.run_detailed('while True: pass')
    assert not r['ok'] and r['error'] == 'Пример выполняется дольше 10 с' and r['seconds'] == 10.0


def test_run_snippet(monkeypatch) -> None:
    """SPEC-SANDBOX-09: run_snippet возвращает None при успехе и текст ошибки при сбое."""
    monkeypatch.setattr(sandbox, 'run_detailed', lambda code: {'ok': code == 'good', 'error': 'E'})
    assert sandbox.run_snippet('good') is None
    assert sandbox.run_snippet('bad') == 'E'


def test_check_examples_limit_and_messages(monkeypatch) -> None:
    """SPEC-SANDBOX-10: check_examples проверяет не больше limit примеров и возвращает ошибки с названием лекции."""
    seen = []

    def fake(code: str):
        seen.append(code)
        return 'упал' if code.startswith('bad') else None

    monkeypatch.setattr(sandbox, 'run_snippet', fake)
    doc = ProgramDoc(id='p', request='x')
    doc.kit.lectures = [
        Lecture(id='l1', topic_id='t', module_id='m', title='Циклы', code_examples=['ok1', 'bad1']),
        Lecture(id='l2', topic_id='t', module_id='m', title='Функции', code_examples=['bad2', 'ok2']),
    ]
    assert sandbox.check_examples(doc, limit=3) == ['Пример к лекции Циклы: упал', 'Пример к лекции Функции: упал']
    assert seen == ['ok1', 'bad1', 'bad2']


LEGIT_EXAMPLES = [
    'print(1)',
    'import math\nprint(math.sqrt(16))',
    'import random\nprint(random.randint(1, 5))',
    'a = int(input())\nprint([x * 2 for x in range(a)])',
    'word = "привет"\nprint(word.upper(), len(word))',
]


@pytest.mark.parametrize('code', LEGIT_EXAMPLES)
def test_legit_examples_still_run(runtime, code) -> None:
    """SPEC-SANDBOX-02: учебные примеры (print, input, math, random, списки, строки) не считаются обращением к системе и выполняются в песочнице."""
    r = sandbox.run_detailed(code)
    assert r['ok'] and r['mode'] == 'run', r['error']


def test_limits_degrade_on_macos(monkeypatch, runtime) -> None:
    """SPEC-SANDBOX-12: WHEN платформа отвергает setrlimit (как RLIMIT_AS на macOS — ValueError «current limit exceeds maximum limit»), THEN лимит пропускается, пример всё равно выполняется (ok, режим run), а отвергнутые лимиты попадают в skipped_limits."""

    def deny(limit, pair):
        raise ValueError('current limit exceeds maximum limit')

    monkeypatch.setattr(resource, 'setrlimit', deny)
    r = sandbox.run_detailed('print(1)')
    assert r['ok'] and r['mode'] == 'run' and r['stdout'].strip() == '1'
    assert r['applied_limits'] == []
    assert set(r['skipped_limits']) == {'RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_NPROC'}


def test_limits_reported(runtime) -> None:
    """SPEC-SANDBOX-13: run_detailed возвращает applied_limits и skipped_limits — имена констант resource, отражающие фактические лимиты дочернего процесса."""
    r = sandbox.run_detailed('print(1)')
    assert r['ok'] and r['mode'] == 'run'
    applied, skipped = set(r['applied_limits']), set(r['skipped_limits'])
    assert not applied & skipped
    if os.name != 'posix':
        assert not applied and skipped == {'RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_NPROC'}
        return
    assert applied | skipped == {'RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_NPROC'}
    assert 'RLIMIT_CPU' in applied
    if sys.platform == 'darwin':
        assert 'RLIMIT_AS' in skipped  # MET-17: macOS не даёт понизить RLIMIT_AS


def test_ast_allowlist_blocks_escape_vectors() -> None:
    """SPEC-SANDBOX-14"""
    from app.validation.sandbox import run_detailed

    # dunder-цепочки ловит первый слой (regex __\w+__)
    r = run_detailed('print((().__class__.__bases__[0].__subclasses__()))')
    assert r['mode'] == 'skip'
    # AST-слой: импорт вне разрешённого списка учебных модулей — только синтаксис, не исполнение
    r2 = run_detailed('import json\nprint(json.dumps({"a": 1}))')
    assert r2['mode'] == 'syntax' and 'json' in r2['error'], r2
    # легитимный учебный пример исполняется как раньше
    r3 = run_detailed('import random\nprint(random.randint(1, 5))')
    assert r3['mode'] == 'run' and r3['ok'] is True
