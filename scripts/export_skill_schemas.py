"""Выгрузка выходных схем навыков в src/app/skills/*/schema_out.json из моделей Pydantic (К-17, Н-12).

    python scripts/export_skill_schemas.py          # записать schema_out.json всех навыков
    python scripts/export_skill_schemas.py --check  # код выхода 1, если файлы расходятся с моделями
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='сверить файлы с моделями, ничего не записывая')
    args = ap.parse_args(argv)
    os.environ.setdefault('LLM_PROVIDERS', 'fixtures')
    sys.path.insert(0, str(ROOT / 'src'))
    from app.skills import outputs

    if args.check:
        if bad := outputs.stale():
            print(f'schema_out.json устарел у навыков: {", ".join(bad)}. Запустите python scripts/export_skill_schemas.py')
            return 1
        print('schema_out.json всех навыков совпадает с моделями')
        return 0
    print(f'Записано schema_out.json: {", ".join(outputs.write_all())}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
