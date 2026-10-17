"""Песочница для примеров кода (V-24): отдельный процесс без сети, с лимитами времени и памяти."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

from app.programs.schemas import ProgramDoc

_TIMEOUT_S = 10
_MEMORY_MB = 512


def _limits() -> None:  # pragma: no cover — выполняется в дочернем процессе
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (_TIMEOUT_S, _TIMEOUT_S))
    mem = _MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


# Всё, чем пример может выйти за пределы учебной задачи: система, сеть, файлы, динамический импорт и eval
_SYSTEM = re.compile(
    r'\b(os|sys|subprocess|socket|shutil|pathlib|ctypes|importlib|builtins|signal|threading|multiprocessing|asyncio|urllib|http|ftplib|pickle|marshal)\b'
    r'|__\w+__|\b(eval|exec|compile|open|getattr|setattr|globals|locals|vars|breakpoint)\s*\('
)

_HEAVY = ('pandas', 'numpy', 'matplotlib', 'seaborn', 'sklearn', 'requests', 'sqlalchemy')


def libraries(code: str) -> list[str]:
    """Импортируемые библиотеки примера."""
    found = re.findall(r'^\s*(?:from|import)\s+([a-zA-Z_][\w]*)', code, flags=re.MULTILINE)
    return list(dict.fromkeys(found))


def run_detailed(code: str) -> dict[str, Any]:
    """Выполняет пример в песочнице: статус, вывод, время, режим (запуск или только синтаксис)."""
    started = time.monotonic()
    res: dict[str, Any] = {'ok': True, 'mode': 'run', 'error': '', 'stdout': '', 'seconds': 0.0}
    if not code.strip():
        return res | {'mode': 'skip'}
    if _SYSTEM.search(code):
        return res | {'mode': 'skip', 'error': 'Пример обращается к системе — не запускается, проверьте вручную'}
    if any(lib in _HEAVY for lib in libraries(code)) or 'sqlite3' in code:
        # Тяжёлые библиотеки проверяются только на синтаксис: в образе ВМ их может не быть
        res['mode'] = 'syntax'
        try:
            compile(code, '<example>', 'exec')
        except SyntaxError as exc:
            res |= {'ok': False, 'error': f'Синтаксическая ошибка: {exc.msg} (строка {exc.lineno})'}
        res['seconds'] = round(time.monotonic() - started, 3)
        return res
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, '-I', '-c', code],
                cwd=tmp,
                capture_output=True,
                timeout=_TIMEOUT_S,
                env={'PATH': '/usr/bin:/bin', 'HTTP_PROXY': 'http://0.0.0.0:9', 'HTTPS_PROXY': 'http://0.0.0.0:9'},
                preexec_fn=_limits if os.name == 'posix' else None,
                input=b'5\n5\n5\n',
            )
        except subprocess.TimeoutExpired:
            return res | {'ok': False, 'error': 'Пример выполняется дольше 10 с', 'seconds': float(_TIMEOUT_S)}
        res['stdout'] = proc.stdout.decode('utf-8', 'ignore')[:800]
        if proc.returncode != 0:
            last = proc.stderr.decode('utf-8', 'ignore').strip().splitlines()[-1:] or ['ошибка']
            res |= {'ok': False, 'error': last[0][:200]}
    res['seconds'] = round(time.monotonic() - started, 3)
    return res


def run_snippet(code: str) -> str | None:
    """Выполняет пример; возвращает текст ошибки или None. Сеть запрещена через пустой прокси."""
    r = run_detailed(code)
    return None if r['ok'] else r['error']


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
