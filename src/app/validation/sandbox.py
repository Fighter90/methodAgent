"""Песочница для примеров кода (V-24): отдельный процесс без сети, с лимитами времени и памяти."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

from app.core.config import get_settings
from app.programs.schemas import ProgramDoc

# Имена констант resource, которые пробуются для дочернего процесса
_LIMIT_NAMES = ('RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_NPROC')


def _limits(timeout_s: int, memory_mb: int) -> tuple[list[str], list[str]]:  # pragma: no cover — дочерний процесс (проверяется через _probe_limits)
    """Устанавливает лимиты дочернего процесса: время CPU, адресное пространство, число процессов.

    Каждый лимит пробуется отдельно: IF платформа не даёт его понизить
    (например, RLIMIT_AS на macOS — ValueError «current limit exceeds maximum limit»:
    hard limit RLIM_INFINITY непривилегированному процессу понижать нельзя),
    THEN лимит молча пропускается, чтобы не срывать запуск примера.
    Возвращает (applied_limits, skipped_limits) — имена констант resource.
    """
    import resource

    mem = memory_mb * 1024 * 1024
    # R01-промежуточно: без записи больших файлов и без core-дампов (уменьшение ущерба при обходе фильтров)
    specs = {
        'RLIMIT_CPU': (timeout_s, timeout_s), 'RLIMIT_AS': (mem, mem), 'RLIMIT_NPROC': (64, 64),
        'RLIMIT_FSIZE': (1024 * 1024, 1024 * 1024), 'RLIMIT_CORE': (0, 0),
    }
    applied: list[str] = []
    skipped: list[str] = []
    for name, pair in specs.items():
        limit = getattr(resource, name, None)
        if limit is None:  # константы нет на этой платформе
            skipped.append(name)
            continue
        try:
            resource.setrlimit(limit, pair)
            applied.append(name)
        except (ValueError, OSError, PermissionError):  # macOS: RLIMIT_AS непонизим; иные отказы платформы
            skipped.append(name)
    return applied, skipped


def _probe_limits(timeout_s: int, memory_mb: int) -> tuple[list[str], list[str]]:
    """Выясняет, какие лимиты платформа позволяет установить, не трогая лимиты самого приложения.

    Проба выполняется в одноразовом fork-процессе: он вызывает _limits и передаёт
    имена применённых и отвергнутых лимитов через канал, затем завершается.
    IF fork недоступен, THEN возвращается пустой отчёт (лимиты неизвестны);
    вне POSIX ни один лимит неприменим, поэтому все попадают в skipped_limits.
    """
    if os.name != 'posix':
        return [], list(_LIMIT_NAMES)
    import resource

    resource.getrlimit(resource.RLIMIT_CPU)  # импортируем модуль в родителе до fork: безопасно для ребёнка
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        return [], []
    if pid == 0:  # ребёнок: проверяет лимиты и сразу завершается
        os.close(read_fd)
        try:
            applied, skipped = _limits(timeout_s, memory_mb)
            os.write(write_fd, f'{",".join(applied)}|{",".join(skipped)}'.encode())
        except BaseException:  # noqa: BLE001 — сбой пробы не должен ломать запуск примера
            pass
        finally:
            os.close(write_fd)
            os._exit(0)
    os.close(write_fd)
    try:
        data = os.read(read_fd, 4096)
        os.waitpid(pid, 0)
    except OSError:
        data = b''
    finally:
        os.close(read_fd)
    try:
        applied_s, skipped_s = data.decode().strip().split('|')
    except ValueError:  # пустой или повреждённый ответ: отчёт неизвестен
        return [], []
    return (
        [name for name in applied_s.split(',') if name],
        [name for name in skipped_s.split(',') if name],
    )


# Всё, чем пример может выйти за пределы учебной задачи: система, сеть, файлы, динамический импорт и eval.
# io, runpy, code, operator добавлены по аудиту песочницы 19.10 (F01): дают интерпретатор и файлы в обход фильтра
_SYSTEM = re.compile(
    r'\b(os|sys|io|runpy|code|operator|subprocess|socket|shutil|pathlib|ctypes|importlib|builtins|signal|threading|multiprocessing|asyncio|urllib|http|ftplib|pickle|marshal)\b'
    r'|__\w+__|\b(eval|exec|compile|open|getattr|setattr|globals|locals|vars|breakpoint)\s*\('
)

_HEAVY = ('pandas', 'numpy', 'matplotlib', 'seaborn', 'sklearn', 'requests', 'sqlalchemy')


def libraries(code: str) -> list[str]:
    """Импортируемые библиотеки примера."""
    found = re.findall(r'^\s*(?:from|import)\s+([a-zA-Z_][\w]*)', code, flags=re.MULTILINE)
    return list(dict.fromkeys(found))


# Разрешённые для исполнения учебные модули (AST-слой, R01-промежуточно): всё вне списка — только синтаксис
_ALLOWED_ROOTS = {'math', 'random', 'string', 'statistics', 'decimal', 'fractions', 'collections', 'itertools', 'functools', 're'}
# Модули, которые разрешённые модули отдают публичным атрибутом (statistics.sys, fractions.operator, re.copyreg)
_MODULE_ATTRS = {'sys', 'os', 'operator', 'numbers', 'copyreg', 'enum', 'types', 'builtins', 'io'}
_BANNED_NAMES = {'eval', 'exec', 'compile', 'open', 'getattr', 'setattr', 'delattr', 'globals', 'locals', 'vars', 'breakpoint', 'memoryview'}


def _ast_risks(code: str) -> list[str]:
    """Конструкции, которые нельзя исполнять: импорты вне разрешённых, dunder-атрибуты и dunder-имена.

    Закрывает известные классы обхода regex-фильтра: цепочки `().__class__.__bases__`,
    `io.FileIO` через частичный импорт, спуфинг имён через alias. Возвращает список причин.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # синтаксические ошибки поймает compile() на своих путях
    risks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] not in _ALLOWED_ROOTS:
                    risks.append(f'импорт модуля {a.name} запрещён')
        elif isinstance(node, ast.ImportFrom):
            if (node.module or '').split('.')[0] not in _ALLOWED_ROOTS:
                risks.append(f'импорт из {node.module} запрещён')
        elif isinstance(node, ast.Attribute):
            # любой «_»-атрибут: random._os, collections._sys и dunder-цепочки дают модуль os в обход списка
            if node.attr.startswith('_'):
                risks.append(f'обращение к служебному атрибуту {node.attr} запрещено')
            elif node.attr in _MODULE_ATTRS:
                risks.append(f'обращение к вложенному модулю {node.attr} запрещено')
        elif isinstance(node, ast.Name):
            if node.id.startswith('__') and node.id.endswith('__'):
                risks.append(f'обращение к служебному имени {node.id} запрещено')
            elif node.id in _BANNED_NAMES:
                # не только вызов: `f = open; f(...)` обходит regex по скобке
                risks.append(f'использование {node.id} запрещено')
    return risks


def run_detailed(code: str) -> dict[str, Any]:
    """Выполняет пример в песочнице: статус, вывод, время, режим (запуск, синтаксис или пропуск).

    Возвращает также applied_limits и skipped_limits — имена констант resource,
    которые удалось и не удалось установить дочернему процессу (например,
    RLIMIT_AS на macOS платформа отвергает); для режимов skip и syntax процесс
    не запускается, и оба списка пустые.
    """
    started = time.monotonic()
    res: dict[str, Any] = {
        'ok': True, 'mode': 'run', 'error': '', 'stdout': '', 'seconds': 0.0,
        'applied_limits': [], 'skipped_limits': [],
    }
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
    # R01 (аудит 22.10): AST-слой — разрешённые импорты и запрет dunder-доступа.
    # Известные обходы regex (().__class__.__bases__, частичные импорты) не доходят до исполнения.
    risks = _ast_risks(code)
    if risks:
        res['mode'] = 'syntax'
        res['error'] = '; '.join(risks[:2]) + ' — пример не запускается, проверьте вручную'
        res['seconds'] = round(time.monotonic() - started, 3)
        return res
    s = get_settings()
    timeout_s, memory_mb = s.sandbox_timeout_s, s.sandbox_memory_mb  # SANDBOX_TIMEOUT_S, SANDBOX_MEMORY_MB
    res['applied_limits'], res['skipped_limits'] = _probe_limits(timeout_s, memory_mb)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, '-I', '-c', code],
                cwd=tmp,
                capture_output=True,
                timeout=timeout_s,
                env={'PATH': '/usr/bin:/bin', 'HTTP_PROXY': 'http://0.0.0.0:9', 'HTTPS_PROXY': 'http://0.0.0.0:9'},
                preexec_fn=(lambda: _limits(timeout_s, memory_mb)) if os.name == 'posix' else None,
                input=b'5\n5\n5\n',
            )
        except subprocess.TimeoutExpired:
            return res | {'ok': False, 'error': f'Пример выполняется дольше {timeout_s} с', 'seconds': float(timeout_s)}
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
