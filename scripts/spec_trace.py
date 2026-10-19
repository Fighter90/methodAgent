"""Трассировка «требование → тест» для спецификаций SDD (specs/README.md).

Читает таблицы требований из specs/*.md (строки, первая ячейка которых — ID вида SPEC-<MODULE>-NN)
и докстринги тестов tests/**/*.py (модуль, классы, функции). Печатает по каждому файлу спецификации:
число требований, сколько из них упомянуто в докстрингах тестов, и непокрытые ID.

Код выхода 1, если тест ссылается на ID, которого нет ни в одной спецификации. Ничего не записывает.

    python scripts/spec_trace.py             # сводка
    python scripts/spec_trace.py --markdown  # таблица трассировки для specs/README.md
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r'\bSPEC-[A-Z][A-Z0-9]*-\d+\b')
ROW_ID_RE = re.compile(r'^SPEC-[A-Z][A-Z0-9]*-\d+$')
TEST_NAME_RE = re.compile(r'\b(test_\w+)\b(?!\.py)')


@dataclass
class Requirement:
    id: str
    spec: str
    declared_tests: list[str] = field(default_factory=list)


@dataclass
class Trace:
    requirements: dict[str, Requirement] = field(default_factory=dict)
    by_spec: dict[str, list[str]] = field(default_factory=dict)
    duplicates: list[tuple[str, str]] = field(default_factory=list)
    refs: dict[str, list[str]] = field(default_factory=dict)  # ID -> ['tests/x.py::test_y', ...]

    @property
    def unknown(self) -> dict[str, list[str]]:
        return {i: where for i, where in sorted(self.refs.items()) if i not in self.requirements}

    def covered(self, spec: str) -> list[str]:
        return [i for i in self.by_spec.get(spec, []) if i in self.refs]

    def uncovered(self, spec: str) -> list[str]:
        return [i for i in self.by_spec.get(spec, []) if i not in self.refs]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip('|').split('|')]


def parse_specs(specs_dir: Path, trace: Trace) -> None:
    for path in sorted(specs_dir.glob('*.md')):
        if path.name.lower() == 'readme.md':
            continue
        ids = trace.by_spec.setdefault(path.name, [])
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.lstrip().startswith('|'):
                continue
            cells = _cells(line)
            first = cells[0].strip('`*_ ')
            if not ROW_ID_RE.match(first):
                continue
            if first in trace.requirements:
                trace.duplicates.append((first, path.name))
                continue
            tests = TEST_NAME_RE.findall(cells[-1]) if len(cells) > 1 else []
            trace.requirements[first] = Requirement(first, path.name, tests)
            ids.append(first)


def parse_tests(tests_dir: Path, trace: Trace) -> None:
    for path in sorted(tests_dir.rglob('*.py')):
        rel = path.relative_to(tests_dir.parent).as_posix()
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        nodes: list[tuple[str, ast.AST]] = [('', tree)]
        nodes += [(n.name, n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]
        for name, node in nodes:
            doc = ast.get_docstring(node) or ''
            where = f'{rel}::{name}' if name else rel
            for i in dict.fromkeys(ID_RE.findall(doc)):
                trace.refs.setdefault(i, []).append(where)


def collect(root: Path = ROOT) -> Trace:
    trace = Trace()
    parse_specs(root / 'specs', trace)
    parse_tests(root / 'tests', trace)
    return trace


def _short(where: str) -> str:
    return where.split('/', 1)[-1]


def mismatches(trace: Trace) -> list[str]:
    """Тест назван в колонке «Тест», но в его докстринге нет ID требования."""
    out = []
    for req in trace.requirements.values():
        names = {w.rsplit('::', 1)[-1] for w in trace.refs.get(req.id, [])}
        out += [f'{req.id}: {t}' for t in req.declared_tests if t not in names]
    return out


def summary(trace: Trace) -> str:
    lines = []
    total = covered = 0
    for spec, ids in trace.by_spec.items():
        cov = trace.covered(spec)
        total, covered = total + len(ids), covered + len(cov)
        lines.append(f'{spec}: требований {len(ids)}, покрыто тестами {len(cov)}')
        if unc := trace.uncovered(spec):
            lines.append(f'  не покрыты: {", ".join(unc)}')
    lines.append(f'ИТОГО: требований {total}, покрыто тестами {covered}')
    for i, spec in trace.duplicates:
        lines.append(f'ПРЕДУПРЕЖДЕНИЕ: {i} объявлен повторно в {spec}')
    for m in mismatches(trace):
        lines.append(f'ПРЕДУПРЕЖДЕНИЕ: колонка «Тест» называет тест без ID в докстринге — {m}')
    for i, where in trace.unknown.items():
        lines.append(f'ОШИБКА: неизвестный ID {i} в {", ".join(where)}')
    return '\n'.join(lines)


def markdown(trace: Trace) -> str:
    lines = ['| Спецификация | Требований | Покрыто | Не покрыты |', '|---|---|---|---|']
    for spec, ids in trace.by_spec.items():
        unc = trace.uncovered(spec)
        lines.append(f'| [{spec}]({spec}) | {len(ids)} | {len(ids) - len(unc)} | {", ".join(unc) or "—"} |')
    lines += ['', '| Требование | Тесты |', '|---|---|']
    for spec, ids in trace.by_spec.items():
        for i in ids:
            tests = ', '.join(f'`{_short(w)}`' for w in trace.refs.get(i, [])) or '—'
            lines.append(f'| {i} | {tests} |')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--markdown', action='store_true', help='печатать таблицу трассировки в Markdown')
    ap.add_argument('--root', type=Path, default=ROOT, help='корень репозитория')
    args = ap.parse_args(argv)
    trace = collect(args.root)
    print(markdown(trace) if args.markdown else summary(trace))
    if trace.unknown:
        if args.markdown:
            print(f'ОШИБКА: неизвестные ID: {", ".join(trace.unknown)}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
