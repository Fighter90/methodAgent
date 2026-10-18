"""Навыки агента в подходе GigaCowork: каталог с SKILL.md, JSON-схемами и run.py.

Оркестратор находит навыки по каталогу, поэтому новый навык добавляется
инструкцией, схемой и тестами без изменения оркестратора (NFR-16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SKILLS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    model_role: str
    temperature: float
    max_tokens: int
    timeout_s: float
    retries: int
    instruction: str
    path: Path


def _parse(path: Path) -> SkillSpec:
    raw = path.read_text(encoding='utf-8')
    _, front, body = raw.split('---', 2)
    meta: dict[str, Any] = yaml.safe_load(front)
    return SkillSpec(
        name=meta['name'],
        description=meta.get('description', ''),
        model_role=meta.get('model_role', 'generate'),
        temperature=float(meta.get('temperature', 0.2)),
        max_tokens=int(meta.get('max_tokens', 2000)),
        timeout_s=float(meta.get('timeout_s', 60)),
        retries=int(meta.get('retries', 2)),
        instruction=body.strip(),
        path=path.parent,
    )


# Параметры навыка, которые администратор меняет в интерфейсе (SKILL.md в образе только для чтения)
EDITABLE = {'temperature': (float, 0.0, 1.0), 'max_tokens': (int, 100, 32000), 'timeout_s': (float, 5.0, 900.0), 'retries': (int, 0, 5)}


def overrides_path() -> Path:
    from app.core.config import get_settings

    return get_settings().data_dir / 'skills_overrides.json'


def load_overrides() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(overrides_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_overrides(data: dict[str, dict[str, Any]]) -> None:
    p = overrides_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    load_skills.cache_clear()


def original_skills() -> dict[str, SkillSpec]:
    return {spec.name: spec for spec in (_parse(md) for md in sorted(SKILLS_DIR.glob('*/SKILL.md')))}


@lru_cache
def load_skills() -> dict[str, SkillSpec]:
    """Все навыки из каталога skills/*/SKILL.md с правками администратора поверх."""
    specs = original_skills()
    for name, ov in load_overrides().items():
        if name in specs:
            fields = {k: v for k, v in ov.items() if k in EDITABLE or k == 'instruction'}
            specs[name] = replace(specs[name], **fields)
    return specs


def skill(name: str) -> SkillSpec:
    return load_skills()[name]
