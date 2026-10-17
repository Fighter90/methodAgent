"""Навык clarify: до 5 вопросов только по пустым обязательным полям (FR-11…FR-13)."""

from __future__ import annotations

from typing import Any

from app.programs.schemas import Assumption, Params, ProgramType, Question

# Значения по умолчанию из профиля АЦР для ответа «На ваше усмотрение»
DEFAULTS: dict[str, Any] = {
    'program_type': ProgramType.DPP_PK,
    'volume_h': 72,
    'audience': 'Взрослые слушатели с базовой компьютерной грамотностью',
    'form': 'очно-заочная',
    'final_assessment_form': 'Защита проекта',
}

_QUESTIONS: dict[str, tuple[str, list[str]]] = {
    'program_type': (
        'Какой это тип программы?',
        ['Повышение квалификации (удостоверение)', 'Общеразвивающая (сертификат)', 'Стажировка'],
    ),
    'volume_h': ('Сколько всего академических часов?', ['36', '72', '144']),
    'audience': (
        'Кто будет учиться и что слушатели уже умеют?',
        ['Без опыта в этой области', 'Знают основы', 'Уже работают в этой сфере'],
    ),
    'form': ('Как проходят занятия?', ['Очно', 'Очно-заочно', 'Дистанционно']),
    'final_assessment_form': (
        'Как проверяем итог обучения?',
        ['Защита проекта', 'Экзамен с практическим заданием', 'Зачёт по тесту'],
    ),
}

DEFAULT_ANSWER = 'На ваше усмотрение'


def missing_fields(p: Params) -> list[str]:
    missing = []
    if p.program_type is None:
        missing.append('program_type')
    if not p.volume_h:
        missing.append('volume_h')
    if not p.audience or not p.entry_level:
        missing.append('audience')
    if not p.form:
        missing.append('form')
    if not p.final_assessment_form:
        missing.append('final_assessment_form')
    return missing


def run(p: Params) -> list[Question]:
    return [
        Question(id=f'q{i + 1}', field=f, text=_QUESTIONS[f][0], options=_QUESTIONS[f][1])
        for i, f in enumerate(missing_fields(p)[:5])
    ]


def apply_answers(p: Params, questions: list[Question], answers: dict[str, str]) -> list[Assumption]:
    """Заполняет параметры ответами; «На ваше усмотрение» берёт значение из профиля."""
    assumptions: list[Assumption] = []
    for q in questions:
        ans = (answers.get(q.id) or answers.get(q.field) or DEFAULT_ANSWER).strip()
        q.answer = ans
        if ans == DEFAULT_ANSWER:
            value = DEFAULTS[q.field]
            assumptions.append(Assumption(field=q.field, value=str(getattr(value, 'value', value)), source='профиль АЦР (на усмотрение агента)'))
            _set(p, q.field, value)
        else:
            _set(p, q.field, ans)
    return assumptions


def fill_defaults(p: Params) -> list[Assumption]:
    """Режим auto: пустые обязательные поля заполняются значениями профиля без вопросов."""
    return apply_answers(p, run(p), {})


def _set(p: Params, field: str, value: Any) -> None:
    low = str(value).lower()
    if field == 'program_type':
        if isinstance(value, ProgramType):
            p.program_type = value
        elif 'стаж' in low:
            p.program_type = ProgramType.DPP_PK_INTERNSHIP
        elif 'общеразв' in low or 'сертиф' in low:
            p.program_type = ProgramType.DOOP
        else:
            p.program_type = ProgramType.DPP_PK
    elif field == 'volume_h':
        digits = ''.join(ch for ch in low if ch.isdigit())
        p.volume_h = int(digits) if digits else int(DEFAULTS['volume_h'])
    elif field == 'audience':
        text = str(value)
        if not p.audience:
            p.audience = text
        if not p.entry_level:
            p.entry_level = text
        elif p.audience == text:
            p.entry_level = text
        else:
            p.audience = f'{p.audience}; {text}' if text not in p.audience else p.audience
    elif field == 'form':
        if 'дистан' in low:
            p.form = 'дистанционная'
        elif 'заоч' in low and 'очно' in low:
            p.form = 'очно-заочная'
        elif 'заоч' in low:
            p.form = 'заочная'
        else:
            p.form = 'очная'
    elif field == 'final_assessment_form':
        p.final_assessment_form = str(value)
