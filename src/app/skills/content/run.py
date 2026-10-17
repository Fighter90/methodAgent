"""Навык content: содержание одного модуля по утверждённому каркасу (FR-25…FR-29).

Модули генерируются параллельно (семафор слоя моделей). Если модель недоступна,
элемент собирается по шаблону из каркаса и помечается для доработки экспертом —
комплект остаётся полным и согласованным.
"""

from __future__ import annotations

import logging

import json

from pydantic import BaseModel, Field

from app.kb.registry import tools
from app.llm.client import CallStats, get_llm
from app.programs.schemas import (
    Criterion,
    Lecture,
    LearningOutcome,
    Module,
    ModuleProgram,
    ProgramDoc,
    ProgramType,
    Question_,
    Slide,
    Task,
)
from app.skills.base import skill


class QuestionLLM(BaseModel):
    stem: str
    options: list[str] = Field(min_length=3, max_length=6)
    key: int
    lo: list[str] = Field(default_factory=list)


class CriterionLLM(BaseModel):
    text: str
    points: int = 2


class TaskLLM(BaseModel):
    topic: str = ''
    title: str = ''
    statement: str
    expected_result: str = ''
    criteria: list[CriterionLLM] = Field(default_factory=list)
    lo: list[str] = Field(default_factory=list)


class SlideLLM(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)


class LectureLLM(BaseModel):
    topic: str
    plan: list[dict] = Field(default_factory=list)
    code: str = ''
    slides: list[SlideLLM] = Field(default_factory=list)


class TopicContentLLM(BaseModel):
    n: str
    content: str = ''


class ModuleContentLLM(BaseModel):
    annotation: str = ''
    topics: list[TopicContentLLM] = Field(default_factory=list)
    questions: list[QuestionLLM] = Field(default_factory=list)
    tasks: list[TaskLLM] = Field(default_factory=list)
    lectures: list[LectureLLM] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ModuleContent(BaseModel):
    program: ModuleProgram
    questions: list[Question_]
    tasks: list[Task]
    lectures: list[Lecture]
    sources: list[str]
    source: str


def _module_los(doc: ProgramDoc, m: Module) -> list[LearningOutcome]:
    ids = {lo_id for t in m.topics for lo_id in t.lo_ids}
    return [lo for lo in doc.all_outcomes() if lo.id in ids]


async def run(
    doc: ProgramDoc,
    m: Module,
    *,
    n_questions: int,
    test_id: str,
    slide_topics: set[str],
    stats: CallStats | None = None,
    instruction_extra: str = '',
) -> ModuleContent:
    los = _module_los(doc, m)
    llm = get_llm()
    need_slides = any(t.id in slide_topics for t in m.topics)
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP
    if llm.enabled:
        spec = skill('content')
        payload = {
            'program': doc.title,
            'program_type': doc.template,
            'audience': f'{doc.params.audience}; входной уровень: {doc.params.entry_level}',
            'constraints': doc.params.constraints,
            'module': {'n': m.n, 'title': m.title, 'hours': m.hours.model_dump(), 'control': m.control},
            'topics': [
                {
                    'n': t.n, 'title': t.title, 'description': t.description, 'hours': t.hours.model_dump(),
                    'has_practice': (t.hours.pr + t.hours.lb > 0) or internship,
                    'lo': [lo.code for lo in los if lo.id in t.lo_ids],
                    'need_slides': t.id in slide_topics,
                }
                for t in m.topics
            ],
            'outcomes': [{'code': lo.code, 'text': lo.text} for lo in los],
            'n_questions': n_questions,
            'need_slides': need_slides,
            'internship': internship,
            'tool_versions_2026': tools()['current'],
            'note': instruction_extra
            or ('Стажировка: задания — практические задания на рабочем месте под руководством наставника.' if internship else ''),
        }
        try:
            data: ModuleContentLLM = await llm.complete_json(
                skill='content',
                system=spec.instruction,
                user=json.dumps(payload, ensure_ascii=False),
                schema=ModuleContentLLM,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens if need_slides else min(spec.max_tokens, 3000),
                stats=stats,
            )
            return _from_llm(doc, m, los, data, n_questions, test_id, slide_topics)
        except Exception as exc:  # noqa: BLE001 — сбой модели или разбора ответа: работает резервная генерация
            logging.getLogger(__name__).warning('%s: резервная генерация (%s: %s)', __name__, type(exc).__name__, str(exc)[:200])
    return fallback(doc, m, los, n_questions, test_id, slide_topics)


def _lo_ids(codes: list[str], los: list[LearningOutcome], default: list[str]) -> list[str]:
    by_code = {lo.code.replace(' ', ''): lo.id for lo in los}
    ids = [by_code[c.replace(' ', '')] for c in codes if c.replace(' ', '') in by_code]
    return ids or default


def _from_llm(
    doc: ProgramDoc, m: Module, los: list[LearningOutcome], data: ModuleContentLLM, n_questions: int, test_id: str, slide_topics: set[str]
) -> ModuleContent:
    topic_by_n = {t.n: t for t in m.topics}
    content_by_n = {tc.n: tc.content for tc in data.topics}
    program = ModuleProgram(
        module_id=m.id,
        annotation=data.annotation or f'Модуль «{m.title}».',
        content=[{'topic_id': t.id, 'text': content_by_n.get(t.n) or t.description} for t in m.topics],
    )
    questions: list[Question_] = []
    for i, q in enumerate(data.questions[:n_questions], start=1):
        default_lo = [los[(i - 1) % len(los)].id] if los else []
        key = q.key if 0 <= q.key < len(q.options) else 0
        questions.append(
            Question_(
                id=f'q{m.n}.{i}', assessment_id=test_id, module_id=m.id, stem=q.stem.strip(),
                options=[o.strip() for o in q.options], key=key, lo_ids=_lo_ids(q.lo, los, default_lo),
            )
        )
    if len(questions) < n_questions:
        extra = fallback(doc, m, los, n_questions, test_id, slide_topics).questions
        questions += extra[len(questions) : n_questions]
        for i, q in enumerate(questions, start=1):
            q.id = f'q{m.n}.{i}'
    tasks: list[Task] = []
    for i, t in enumerate(data.tasks, start=1):
        topic = topic_by_n.get(t.topic) or (m.topics[(i - 1) % len(m.topics)] if m.topics else None)
        criteria = [Criterion(text=c.text, points=max(1, c.points)) for c in t.criteria] or _default_criteria()
        tasks.append(
            Task(
                id=f'task{m.n}.{i}', assessment_id=f'sem-{m.id}', module_id=m.id, topic_id=topic.id if topic else None,
                title=t.title or (f'Задание к теме {topic.n}' if topic else f'Задание {i}'), statement=t.statement,
                expected_result=t.expected_result, criteria=criteria,
                lo_ids=_lo_ids(t.lo, los, topic.lo_ids if topic else []),
            )
        )
    if not tasks:
        tasks = fallback(doc, m, los, n_questions, test_id, slide_topics).tasks
    lectures: list[Lecture] = []
    lec_by_topic = {lec.topic: lec for lec in data.lectures}
    for t in m.topics:
        if t.id not in slide_topics:
            continue
        lec = lec_by_topic.get(t.n)
        if lec is None or not lec.slides:
            lectures.append(_fallback_lecture(m, t))
            continue
        slides = [Slide(id=f'sl{t.n}.{j}', n=j, title=s.title, bullets=s.bullets[:6]) for j, s in enumerate(lec.slides[:8], start=1)]
        plan = [{'min': int(p.get('min', 10) or 10), 'text': str(p.get('text', ''))} for p in lec.plan if isinstance(p, dict)]
        lectures.append(
            Lecture(
                id=f'lec{t.n}', topic_id=t.id, module_id=m.id, title=t.title, duration_min=max(45, t.hours.lk * 45),
                plan=plan or _default_plan(t.title), code_examples=[lec.code] if lec.code else [], slides=slides,
            )
        )
    return ModuleContent(program=program, questions=questions, tasks=tasks, lectures=lectures, sources=data.sources[:3], source='llm')


def _default_criteria() -> list[Criterion]:
    return [
        Criterion(text='Задание выполнено полностью и в срок', points=4),
        Criterion(text='Решение корректно и воспроизводимо', points=4),
        Criterion(text='Результат оформлен и пояснён', points=2),
    ]


def _default_plan(title: str) -> list[dict]:
    return [
        {'min': 10, 'text': f'Актуализация: зачем нужна тема «{title}»'},
        {'min': 40, 'text': 'Основные понятия и разбор примеров'},
        {'min': 30, 'text': 'Демонстрация и практическое упражнение'},
        {'min': 10, 'text': 'Итоги, вопросы, задание для самостоятельной работы'},
    ]


def _fallback_lecture(m: Module, t) -> Lecture:  # noqa: ANN001
    slides = [
        Slide(id=f'sl{t.n}.1', n=1, title=t.title, bullets=[f'Модуль {m.n}. {m.title}', f'Тема {t.n}']),
        Slide(id=f'sl{t.n}.2', n=2, title='Зачем это нужно', bullets=[t.description or t.title, 'Где применяется на практике']),
        Slide(id=f'sl{t.n}.3', n=3, title='Ключевые понятия', bullets=[p.strip() for p in (t.description or t.title).split(',')][:4]),
        Slide(id=f'sl{t.n}.4', n=4, title='Практика', bullets=['Разбор примера вместе с преподавателем', 'Самостоятельное упражнение']),
        Slide(id=f'sl{t.n}.5', n=5, title='Итоги', bullets=['Что мы узнали', 'Задание к следующему занятию']),
    ]
    return Lecture(
        id=f'lec{t.n}', topic_id=t.id, module_id=m.id, title=t.title, duration_min=max(45, t.hours.lk * 45),
        plan=_default_plan(t.title), slides=slides,
    )


def fallback(doc: ProgramDoc, m: Module, los: list[LearningOutcome], n_questions: int, test_id: str, slide_topics: set[str]) -> ModuleContent:
    """Шаблонное содержание из каркаса: структура полная, текст — черновик для эксперта."""
    program = ModuleProgram(
        module_id=m.id,
        annotation=f'Модуль «{m.title}» формирует результаты обучения: ' + '; '.join(lo.text for lo in los[:4]) + '.',
        content=[{'topic_id': t.id, 'text': t.description or t.title} for t in m.topics],
        control_questions=[f'Раскройте содержание темы «{t.title}».' for t in m.topics],
    )
    questions: list[Question_] = []
    for i in range(n_questions):
        lo = los[i % len(los)] if los else None
        topic = m.topics[i % len(m.topics)]
        correct = lo.text if lo else topic.description or topic.title
        options = [
            correct,
            f'Тема «{topic.title}» не связана с практикой',
            'Ни один из вариантов не относится к модулю',
            'Это делается только вручную без инструментов',
        ]
        key = i % 4
        options[0], options[key] = options[key], options[0]
        questions.append(
            Question_(
                id=f'q{m.n}.{i + 1}', assessment_id=test_id, module_id=m.id,
                stem=f'Что относится к результату изучения темы «{topic.title}»?',
                options=options, key=key, lo_ids=[lo.id] if lo else [],
            )
        )
    tasks = []
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP
    for i, t in enumerate(m.topics, start=1):
        if not internship and t.hours.pr + t.hours.lb == 0:
            continue
        tasks.append(
            Task(
                id=f'task{m.n}.{i}', assessment_id=f'sem-{m.id}', module_id=m.id, topic_id=t.id,
                title=f'{"Задание стажировки" if internship else "Практическое задание"} к теме {t.n}',
                statement=f'Выполните практическую работу по теме «{t.title}»: {t.description or "решите прикладную задачу"}.',
                expected_result='Работающее решение и краткий отчёт о выполнении',
                criteria=_default_criteria(), lo_ids=list(t.lo_ids),
            )
        )
    lectures = [_fallback_lecture(m, t) for t in m.topics if t.id in slide_topics]
    return ModuleContent(program=program, questions=questions, tasks=tasks, lectures=lectures, sources=[], source='template')
