"""Навык intake: параметры запроса.

Числа (объём, срок, нагрузка, число вопросов) извлекает код по шаблонам — это
надёжно и бесплатно. Модель дополняет смысловые поля: аудиторию, темы, ограничения.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from app.llm.client import MODEL_DATA_ERRORS, CallStats, LLMUnavailable, get_llm
from app.programs.schemas import Materials, Params, ProgramType
from app.skills.base import skill

_NUM_WORDS = {
    'один': 1, 'одну': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6,
    'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10, 'двенадцать': 12, 'пятнадцать': 15, 'двадцать': 20,
    'двух': 2, 'трех': 3, 'четырех': 4, 'пяти': 5, 'шести': 6,
}


def _num(token: str) -> float | None:
    token = token.lower().strip()
    if token in _NUM_WORDS:
        return float(_NUM_WORDS[token])
    try:
        return float(token.replace(',', '.'))
    except ValueError:
        return None


_N = r'(\d+(?:[.,]\d+)?|один|одну|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|двенадцать|двух|трех|четырех|пяти|шести)'


class IntakeLLM(BaseModel):
    title: str = ''
    direction: str = ''
    audience: str = ''
    entry_level: str = ''
    form: str = ''
    final_assessment_form: str = ''
    required_topics: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    customer_expectation: str = ''


# Аудитория-дети: общеразвивающая программа (приказ № 629), даже если тип не назван
_CHILD = re.compile(r'школьник|подрост|\bдет(ей|и|ям|ский)\b|\bребен|\b\d{1,2}\s*(?:-|–)?\s*(?:\d{1,2}\s*)?класс')
_AGES = re.compile(r'\b(\d{1,2})\s*(?:-|–|до)\s*(\d{1,2})\s*лет\b')


def _is_child_audience(low: str) -> bool:
    if _CHILD.search(low):
        return True
    m = _AGES.search(low)
    return bool(m and int(m.group(2)) <= 17)


def parse_numbers(text: str) -> Params:
    """Детерминированный разбор чисел и ключевых слов запроса."""
    low = text.lower().replace('ё', 'е')
    p = Params()

    # Тип программы
    if 'общеразвива' in low or re.search(r'\bдооп\b', low):
        p.program_type = ProgramType.DOOP
    elif 'стажировк' in low:
        p.program_type = ProgramType.DPP_PK_INTERNSHIP
    elif 'повышени' in low and 'квалификац' in low or 'переподготовк' in low or re.search(r'\b(дпп|пк|пп)\b', low):
        p.program_type = ProgramType.DPP_PK
    elif _is_child_audience(low):
        p.program_type = ProgramType.DOOP

    # Название в кавычках
    m = re.search(r'[«"]([^»"]{3,120})[»"]', text)
    if m:
        p.title = m.group(1).strip()

    # Нагрузка в день / занятия в неделю
    m = re.search(_N + r'\s*(?:академических\s+|астрономических\s+)?час\w*\s+в\s+день', low)
    if m:
        p.max_hours_per_day = int(_num(m.group(1)) or 0) or None
    m = re.search(r'по\s+' + _N + r'\s*(?:академическ\w+\s+)?час\w*\s+' + _N + r'\s+раз\w*\s+в\s+неделю', low)
    if m:
        p.session_hours = int(_num(m.group(1)) or 0) or None
        p.sessions_per_week = int(_num(m.group(2)) or 0) or None

    # Итоговая аттестация: «аттестация занимает 2 часа»
    m = re.search(r'аттестац\w*[^.]{0,40}?' + _N + r'\s*час', low)
    if m:
        p.final_assessment_hours = int(_num(m.group(1)) or 0) or None

    # Объём: числа с «час», исключая нагрузку в день/неделю, «по N часа», часы ИА
    # и числа из упоминаний образца/референса (F07: «36 часов по образцу 248 часов» — объём 36, а не 248)
    _REF_MARK = re.compile(r'(стар\w+|прошл\w+|образц\w*|референс\w*|пример\w*|возьмите)[^.;!?,\n]{0,60}$')
    candidates = []
    for mm in re.finditer(_N + r'[\s-]*(?:академическ\w+\s+|астрономическ\w+\s+)?(?:час|ч\b)', low):
        start, end = mm.span()
        after = low[end : end + 25]
        before = low[max(0, start - 12) : start]
        if re.match(r'\w*\s+в\s+(день|неделю)', after) or re.search(r'\bпо\s+$', before):
            continue
        if re.search(r'(занимает|длится)\s+$', low[max(0, start - 15) : start]):
            continue
        val = _num(mm.group(1))
        if val:
            if _REF_MARK.search(low[max(0, start - 70) : start]):
                p.reference_volume_h = int(val)
                continue
            candidates.append(int(val))
    if candidates:
        p.volume_h = max(candidates)
        if p.final_assessment_hours and p.volume_h == p.final_assessment_hours and len(candidates) == 1:
            p.volume_h = None

    # Срок
    m = re.search(r'(?:срок\w*|за|около|примерно|на)\s*(?:около\s+|примерно\s+)?' + _N + r'\s*(недел|месяц)', low)
    if m:
        val = _num(m.group(1)) or 1
        p.duration_weeks = val if m.group(2).startswith('недел') else round(val * 4.3, 1)
    elif re.search(r'(примерно|около)?\s*на\s+месяц|за\s+месяц', low):
        p.duration_weeks = 4.3
    elif 'двух месяцев' in low or 'два месяца' in low:
        p.duration_weeks = 8.6

    # Форма обучения
    if 'очно-заочн' in low:
        p.form = 'очно-заочная'
    elif 'заочн' in low:
        p.form = 'заочная'
    elif 'дистанцион' in low and 'очно' not in low:
        p.form = 'дистанционная'
    elif re.search(r'\bочн', low):
        p.form = 'очная'
    p.distance = 'дистанцион' in low or 'дот' in low.split()
    p.no_classroom = 'аудиторных занятий нет' in low or 'вся работа самостоятельн' in low
    if p.no_classroom and not p.form:
        p.form = 'очная (стажировка на рабочем месте)'

    # Практика «не меньше половины»
    if re.search(r'практик\w*[^.]{0,30}не\s+меньше\s+половины', low):
        p.min_practice_share = 0.5

    # Материалы: «итоговый тест на 10 вопросов», «слайды для первых двух занятий», «слайды для модуля про pandas»
    mat = Materials()
    m = re.search(r'тест\w*\s+(?:на|из)\s+' + _N + r'\s+вопрос', low)
    if m:
        mat.test_questions = int(_num(m.group(1)) or 0) or None
    m = re.search(r'слайд\w*\s+для\s+(?:перв\w+\s+)?' + _N + r'?\s*(?:перв\w+\s+)?заняти', low)
    if m:
        n = int(_num(m.group(1)) or 2) if m.group(1) else 1
        mat.slides_lessons = list(range(1, n + 1))
    m = re.search(r'слайд\w*\s+(?:нужны\s+)?для\s+модул\w*\s+(?:про|по)\s+([\w\-]+)', low)
    if m:
        mat.slides_topic_hint = m.group(1)
    p.materials = mat

    # Итоговая аттестация: форма
    for pattern, form in (
        (r'защи(?:т|щ)\w*\s+(?:\w+\s+){0,2}проект', 'Защита проекта'),
        (r'защит\w*\s+отч[её]т', 'Защита отчёта о стажировке'),
        (r'зач[её]т\w*\s+по\s+портфолио', 'Зачёт по портфолио'),
        (r'экзамен', 'Экзамен'),
        (r'зач[её]т', 'Зачёт'),
        (r'тестировани', 'Итоговое тестирование'),
    ):
        if re.search(pattern, low):
            p.final_assessment_form = form
            break
    if p.final_assessment_form == 'Экзамен' and 'практическ' in low:
        p.final_assessment_form = 'Экзамен с практическим заданием'

    if 'прикладываю' in low or 'образец' in low or 'возьмите за образец' in low or 'прошлую программу' in low:
        p.reference_used = True
    if 'доступны в росси' in low or 'доступны в рф' in low:
        p.constraints.append('Только сервисы, доступные в России')
    if 'обезличен' in low:
        p.constraints.append('Только обезличенные данные')
    m = re.search(r'чтобы\s+(?:после\s+него\s+)?([^.]{5,120})', low)
    if m and ('работ' in m.group(1)):
        p.customer_expectation = m.group(1).strip()
    return p


async def run(text: str, references_text: str = '', stats: CallStats | None = None) -> tuple[Params, bool]:
    """Возвращает параметры и признак того, что модель участвовала в разборе."""
    params = parse_numbers(text)
    llm = get_llm()
    used_llm = False
    if llm.enabled:
        spec = skill('intake')
        payload = {'request': text[:5000], 'reference_excerpt': references_text[:1500]}
        try:
            data: IntakeLLM = await llm.complete_json(
                skill='intake',
                system=spec.instruction,
                user=json.dumps(payload, ensure_ascii=False),
                schema=IntakeLLM,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                stats=stats,
            )
            used_llm = True
            params.title = params.title or data.title
            params.direction = data.direction
            params.audience = data.audience
            params.entry_level = data.entry_level
            params.form = params.form or _norm_form(data.form)
            params.final_assessment_form = params.final_assessment_form or data.final_assessment_form
            params.required_topics = data.required_topics[:12]
            params.constraints = list(dict.fromkeys(params.constraints + data.constraints))[:8]
            params.customer_expectation = params.customer_expectation or data.customer_expectation
        except LLMUnavailable as exc:
            logging.getLogger(__name__).warning('intake: эвристический разбор запроса (%s)', str(exc)[:200])
            if stats is not None:
                stats.fallback('intake', exc, 'эвристический разбор запроса')
        except MODEL_DATA_ERRORS as exc:
            logging.getLogger(__name__).exception('intake: ответ модели не разобран, эвристический разбор')
            if stats is not None:
                stats.fallback('intake', exc, 'эвристический разбор запроса')
    if not used_llm:
        _heuristic_semantics(text, params)
    return params, used_llm


def _norm_form(form: str) -> str:
    low = form.lower()
    for key in ('очно-заочная', 'заочная', 'дистанционная', 'очная'):
        if key[:5] in low:
            return key
    return ''


def _heuristic_semantics(text: str, p: Params) -> None:
    """Смысловые поля без модели: аудитория, темы, направление."""
    low = text.lower()
    m = re.search(r'\bдля\s+([^.,]{5,90}?)(?:[.,]|\s+без\s+|\s+которые|\s+объ[её]м|\s+\d)', text)
    if m:
        p.audience = m.group(1).strip()
    m = re.search(r'без\s+опыта\s+([\w\s]{3,40})', low)
    if m:
        p.entry_level = 'Без опыта ' + m.group(1).strip()
    m = re.search(r'(?:знают|умеют|работают\s+в)\s+([^.]{3,80})', low)
    if m and not p.entry_level:
        p.entry_level = m.group(0).strip().capitalize()
    m = re.search(r'(?:основные\s+темы|темы)\s*(?:это|:|—|-)?\s*([^.]{5,200})', text, flags=re.IGNORECASE)
    if m:
        parts = re.split(r',\s*|\s+и\s+', m.group(1))
        p.required_topics = [x.strip(' .') for x in parts if 2 < len(x.strip()) < 60][:10]
    p.direction = p.title or (p.required_topics[0] if p.required_topics else '') or _direction_phrase(low)


def _direction_phrase(low: str) -> str:
    """Направление из оборота «курс (программа) по …», когда нет названия в кавычках и перечня тем."""
    m = re.search(r'(?:курс\w*|программ\w*|обучени\w*)\s+по\s+([^.,;:!?\d]{3,60}?)(?=\s+(?:для|на|в|с|со|от|до)\s|[.,;:!?]|$)', low)
    return m.group(1).strip() if m else ''
