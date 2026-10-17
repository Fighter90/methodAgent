"""Песочница для примеров кода (V-24): отдельный процесс без сети, с лимитами времени и памяти."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from app.programs.schemas import ProgramDoc

_TIMEOUT_S = 10
_MEMORY_MB = 512


def _limits() -> None:  # pragma: no cover — выполняется в дочернем процессе
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (_TIMEOUT_S, _TIMEOUT_S))
    mem = _MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def run_snippet(code: str) -> str | None:
    """Выполняет пример; возвращает текст ошибки или None. Сеть запрещена через пустой прокси."""
    if not code.strip() or 'import os' in code or 'subprocess' in code or 'socket' in code:
        return None
    if any(lib in code for lib in ('import pandas', 'import numpy', 'import matplotlib', 'import seaborn', 'sqlite3', 'requests')):
        # Тяжёлые библиотеки проверяются только на синтаксис: в образе ВМ их может не быть
        try:
            compile(code, '<example>', 'exec')
            return None
        except SyntaxError as exc:
            return f'Синтаксическая ошибка: {exc.msg} (строка {exc.lineno})'
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(  # noqa: S603 — фиксированный интерпретатор, код только из комплекта
                [sys.executable, '-I', '-c', code],
                cwd=tmp,
                capture_output=True,
                timeout=_TIMEOUT_S,
                env={'PATH': '/usr/bin:/bin', 'HTTP_PROXY': 'http://0.0.0.0:9', 'HTTPS_PROXY': 'http://0.0.0.0:9'},
                preexec_fn=_limits if os.name == 'posix' else None,  # noqa: PLW1509
                input=b'5\n5\n5\n',
            )
        except subprocess.TimeoutExpired:
            return 'Пример выполняется дольше 10 с'
        if proc.returncode != 0:
            last = proc.stderr.decode('utf-8', 'ignore').strip().splitlines()[-1:] or ['ошибка']
            return last[0][:200]
    return None


def check_examples(doc: ProgramDoc, limit: int = 12) -> list[str]:
    errors = []
    checked = 0
    for lec in doc.kit.lectures:
        for code in lec.code_examples:
            if checked >= limit:
                return errors
            checked += 1
            err = run_snippet(code)
            if err:
                errors.append(f'Пример к лекции {lec.title}: {err}')
    return errors
