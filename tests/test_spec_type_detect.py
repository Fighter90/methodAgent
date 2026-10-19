"""Определение типа программы по сокращениям и аудитории (SPEC-SKILLS-15)."""

import pytest

from app.programs.schemas import ProgramType
from app.skills.intake.run import parse_numbers


@pytest.mark.parametrize(('text', 'expected'), [
    ('ДООП «Скретч для младших школьников 7-9 лет», 36 часов', ProgramType.DOOP),
    ('ДООП «Разработка игр на Unity», 72 часа', ProgramType.DOOP),
    ('Курс «Робототехника» для ребят 10–14 лет, 72 часа', ProgramType.DOOP),
    ('Курс по Python для 8 класса', ProgramType.DOOP),
    ('ПК «Frontend-разработка на React», 72 часа', ProgramType.DPP_PK),
    ('ПП «Специалист по кибербезопасности», 512 часов', ProgramType.DPP_PK),
    ('ДПП «Аналитика данных», 40 часов', ProgramType.DPP_PK),
    ('Стажировка «DevOps», 256 часов', ProgramType.DPP_PK_INTERNSHIP),
    ('Курс для студентов 18-25 лет', None),
    ('Сделайте курс по кибербезопасности для студентов колледжа', None),
    ('Программа для специалистов, доп. модуль', None),
])
def test_type_from_abbreviations_and_audience(text: str, expected: ProgramType | None) -> None:
    """SPEC-SKILLS-15: тип программы по сокращениям и детской аудитории, иначе пусто и вопрос методисту."""
    assert parse_numbers(text).program_type == expected
