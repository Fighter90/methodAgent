"""Выходные схемы навыков `skills/*/schema_out.json` (К-17, Н-12): генерируются из типов, которые возвращает навык.

Файлы сверяются с кодом тестом `test_spec_skill_schemas.py` и скриптом `scripts/export_skill_schemas.py --check`.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.skills.base import SKILLS_DIR

DRAFT = 'https://json-schema.org/draft/2020-12/schema'


class ExportFile(BaseModel):
    """Навык export отдаёт файл; схема описывает его метаданные (тело — байты файла в ответе GET /export/{fmt})."""

    format: Literal['docx', 'pptx', 'gift', 'moodle_xml', 'json', 'order_draft', 'lectures_docx']
    filename: str = Field(description='Имя файла из заголовка Content-Disposition')
    media_type: str = Field(description='Тип содержимого ответа')


def output_types() -> dict[str, Any]:
    """Навык → тип результата его функции (импорт ленивый: модули навыков тянут слой моделей)."""
    from app.programs.schemas import Params, ProgramDoc, Question, Report
    from app.skills.classify.run import ClassifyResult
    from app.skills.content.run import ModuleContent
    from app.skills.review_assist.run import Proposal
    from app.skills.skeleton.run import SkeletonDraft
    from app.solver.hours import SolverResult

    return {
        'intake': Params,  # skills/intake/run.py (run)
        'classify': ClassifyResult,  # skills/classify/run.py (run)
        'clarify': list[Question],  # skills/clarify/run.py (run)
        'skeleton': SkeletonDraft,  # skills/skeleton/run.py (run)
        'hours_solver': SolverResult,  # solver/hours.py (solve)
        'content': ModuleContent,  # skills/content/run.py (run)
        'validate': Report,  # validation/report.py (build_report) с вердиктом судьи
        'repair': list[str],  # validation/repair.py (repair): что исправлено
        'review_assist': Proposal,  # skills/review_assist/run.py (propose_full)
        'export': ExportFile,  # export/service.py
        'workflow': ProgramDoc,  # состояние программы после шага (programs/service.py, save)
    }


def schema_out(name: str) -> dict[str, Any]:
    schema = TypeAdapter(output_types()[name]).json_schema()
    return {'$schema': DRAFT, 'title': schema.pop('title', f'{name} output'), **schema}


def render(name: str) -> str:
    return json.dumps(schema_out(name), ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def stale() -> list[str]:
    """Навыки, у которых schema_out.json нет или он расходится с моделью."""
    out = []
    for name in output_types():
        f = SKILLS_DIR / name / 'schema_out.json'
        if not f.exists() or f.read_text(encoding='utf-8') != render(name):
            out.append(name)
    return out


def write_all() -> list[str]:
    for name in output_types():
        (SKILLS_DIR / name / 'schema_out.json').write_text(render(name), encoding='utf-8')
    return list(output_types())
