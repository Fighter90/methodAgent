"""Навыки агента в подходе GigaCowork: каталог с SKILL.md, JSON-схемами и run.py.

Оркестратор находит навыки по каталогу, поэтому новый навык добавляется
инструкцией, схемой и тестами без изменения оркестратора (NFR-16).
"""

from __future__ import annotations

from dataclasses import dataclass
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


@lru_cache
def load_skills() -> dict[str, SkillSpec]:
    """Все навыки из каталога skills/*/SKILL.md."""
    specs = {}
    for md in sorted(SKILLS_DIR.glob('*/SKILL.md')):
        spec = _parse(md)
        specs[spec.name] = spec
    return specs


def skill(name: str) -> SkillSpec:
    return load_skills()[name]
