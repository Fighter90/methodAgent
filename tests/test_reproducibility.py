"""Воспроизводимость сборки: закреплённые базовые образы, lock-файлы с хэшами, версии интерпретаторов."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ_LINE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)')


def _norm(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def _pins(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        m = REQ_LINE.match(line.strip())
        if m:
            out[_norm(m.group(1))] = m.group(2)
    return out


def test_images_pinned_and_lock_files_cover_requirements() -> None:
    """SPEC-API-27: базовые образы Dockerfile закреплены по digest, образ ставит requirements.lock с --require-hashes, lock-файлы содержат каждый пакет requirements*.txt той же версии и хэш у каждого пакета."""
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    froms = [ln.split()[1] for ln in dockerfile.splitlines() if ln.startswith('FROM ')]
    assert len(froms) >= 2
    for image in froms:
        assert re.search(r'@sha256:[0-9a-f]{64}$', image), image
    assert re.search(r'pip install .*--require-hashes -r requirements\.lock', dockerfile)
    assert 'COPY requirements.lock' in dockerfile and 'npm ci' in dockerfile

    for src, lock in (('requirements.txt', 'requirements.lock'), ('requirements-dev.txt', 'requirements-dev.lock')):
        lock_path = ROOT / lock
        assert lock_path.exists(), lock
        locked = _pins(lock_path)
        direct = _pins(ROOT / src)
        if src == 'requirements-dev.txt':
            direct |= _pins(ROOT / 'requirements.txt')
        missing = {n: v for n, v in direct.items() if locked.get(n) != v}
        assert not missing, f'{lock} устарел относительно {src}: {missing}'
        # у каждого закреплённого пакета есть хэш
        blocks = re.split(r'\n(?=[A-Za-z0-9])', lock_path.read_text(encoding='utf-8'))
        for block in blocks:
            if REQ_LINE.match(block):
                assert '--hash=sha256:' in block, block.splitlines()[0]

    assert (ROOT / '.python-version').read_text().strip() == '3.12'
    assert (ROOT / '.nvmrc').read_text().strip() == '22'
    pkg = json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))
    assert pkg['engines']['node'].startswith('>=22')
    assert (ROOT / 'frontend' / 'package-lock.json').exists()


def test_openapi_schema_matches_code() -> None:
    """SPEC-API-28: docs/openapi.json совпадает со схемой приложения, CI сверяет её и запускает ESLint и vitest интерфейса."""
    import importlib.util

    spec = importlib.util.spec_from_file_location('export_openapi', ROOT / 'scripts' / 'export_openapi.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.OUT.read_text(encoding='utf-8') == mod.render()
    ci = (ROOT / '.gitea' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    assert 'export_openapi.py --check' in ci and 'npm run check' in ci
    scripts = json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))['scripts']
    assert 'eslint' in scripts['lint'] and 'vitest' in scripts['test']
    assert 'lint' in scripts['check'] and 'test' in scripts['check']
