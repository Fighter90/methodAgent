"""Выходные схемы навыков: skills/*/schema_out.json существуют и совпадают с моделями Pydantic (К-17, Н-12)."""

from __future__ import annotations

import json
import os

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.skills import outputs  # noqa: E402
from app.skills.base import SKILLS_DIR, original_skills  # noqa: E402


def test_schema_out_matches_models() -> None:
    """SPEC-SKILLS-16: у каждого навыка есть schema_out.json, на который ссылается SKILL.md; файл совпадает со схемой модели результата (scripts/export_skill_schemas.py --check)."""
    skills = original_skills()
    assert set(outputs.output_types()) == set(skills)
    for name in skills:
        md = (SKILLS_DIR / name / 'SKILL.md').read_text(encoding='utf-8')
        assert 'output: schema_out.json' in md
        data = json.loads((SKILLS_DIR / name / 'schema_out.json').read_text(encoding='utf-8'))
        assert data['$schema'] == outputs.DRAFT and data['title']
    assert outputs.stale() == []


def test_export_script_check(tmp_path, monkeypatch) -> None:
    """SPEC-SKILLS-16: скрипт --check возвращает 0 для актуальных файлов и 1, если файл устарел."""
    import importlib.util

    spec = importlib.util.spec_from_file_location('export_skill_schemas', SKILLS_DIR.parents[2] / 'scripts' / 'export_skill_schemas.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(['--check']) == 0
    monkeypatch.setattr(outputs, 'render', lambda name: '{}\n')
    assert mod.main(['--check']) == 1
