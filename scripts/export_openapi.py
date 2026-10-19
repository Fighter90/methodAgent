"""Выгрузка схемы OpenAPI в docs/openapi.json (ТЗ 4.11, T-25).

    python scripts/export_openapi.py          # записать docs/openapi.json
    python scripts/export_openapi.py --check  # код выхода 1, если файл расходится с кодом
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'openapi.json'


def render() -> str:
    os.environ.setdefault('LLM_PROVIDERS', 'fixtures')
    sys.path.insert(0, str(ROOT / 'src'))
    from app.main import app

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='сверить файл с кодом, ничего не записывая')
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding='utf-8') != text:
            print(f'{OUT.relative_to(ROOT)} устарел: запустите python scripts/export_openapi.py')
            return 1
        print(f'{OUT.relative_to(ROOT)} совпадает с кодом')
        return 0
    OUT.write_text(text, encoding='utf-8')
    print(f'Записано {OUT.relative_to(ROOT)}: {len(json.loads(text)["paths"])} путей')
    return 0


if __name__ == '__main__':
    sys.exit(main())
