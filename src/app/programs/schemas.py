"""Модель данных комплекта: граф с устойчивыми идентификаторами (ТЗ, подраздел 4.8).

Связи «компетенция → индикатор → РО → тема → лекция, слайд, вопрос, задание»
позволяют проверять покрытие (V-12…V-14) и пересобирать только потомков узла.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProgramType(StrEnum):
    DPP_PK = 'dpp_pk'
    DPP_PK_INTERNSHIP = 'dpp_pk_internship'
    DOOP = 'doop'


class Status(StrEnum):
    DRAFT = 'draft'
    QUESTIONS = 'questions'
    SKELETON = 'skeleton'
    SKELETON_APPROVED = 'skeleton_approved'
    GENERATING = 'generating'
    KIT_READY = 'kit_ready'
    ON_REVIEW = 'on_review'
    ON_APPROVAL = 'on_approval'
    APPROVED = 'approved'
    RETURNED = 'returned'
    FAILED = 'failed'


class Hours(BaseModel):
    total: int = 0
    lk: int = 0
    pr: int = 0
    lb: int = 0
    srs: int = 0

    def kinds_sum(self) -> int:
        return self.lk + self.pr + self.lb + self.srs

    @property
    def contact(self) -> int:
        return self.lk + self.pr + self.lb


KINDS: tuple[str, ...] = ('lk', 'pr', 'lb', 'srs')


class Assumption(BaseModel):
    field: str
    value: Any
    source: str


class FinalAssessment(BaseModel):
    form: str = ''
    hours: int = 0
    description: str = ''


class Materials(BaseModel):
    """Что запрошено в комплекте явно (V-09)."""

    test_questions: int | None = None  # число вопросов итогового теста
    slides_modules: list[int] = Field(default_factory=list)
    slides_lessons: list[int] = Field(default_factory=list)  # номера занятий для ДООП
    slides_topic_hint: str = ''  # «модуль про pandas» — привязываем после каркаса


class Params(BaseModel):
    """Распознанные параметры запроса (навык intake)."""

    program_type: ProgramType | None = None
    title: str = ''
    direction: str = ''
    volume_h: int | None = None
    audience: str = ''
    entry_level: str = ''
    form: str = ''
    duration_weeks: float | None = None
    sessions_per_week: int | None = None
    session_hours: int | None = None
    max_hours_per_day: int | None = None
    days_per_week: int | None = None
    final_assessment_form: str = ''
    final_assessment_hours: int | None = None
    required_topics: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    min_practice_hours: int | None = None
    min_practice_share: float | None = None
    distance: bool = False
    no_classroom: bool = False
    customer_expectation: str = ''
    materials: Materials = Field(default_factory=Materials)
    reference_used: bool = False
    reference_volume_h: int | None = None  # часы из упоминания образца/референса — не объём новой программы (F07)
    reference_structure_only: bool = True
    ps_hint: str = ''


class Question(BaseModel):
    id: str
    field: str
    text: str
    options: list[str] = Field(default_factory=list)
    allow_custom: bool = True
    answer: str | None = None


class TrudFunction(BaseModel):
    code: str
    title: str


class ProfStandard(BaseModel):
    code: str
    title: str
    order: str
    confirmed: bool = True
    tf: list[TrudFunction] = Field(default_factory=list)


class LearningOutcome(BaseModel):
    id: str
    code: str
    text: str
    verb: str = ''
    bloom_level: int = 2


class Indicator(BaseModel):
    id: str
    kind: Literal['know', 'can', 'own']
    text: str
    outcomes: list[LearningOutcome] = Field(default_factory=list)


class Competency(BaseModel):
    id: str
    code: str
    title: str
    ps_code: str | None = None
    tf_codes: list[str] = Field(default_factory=list)
    indicators: list[Indicator] = Field(default_factory=list)


class Topic(BaseModel):
    id: str
    n: str
    title: str
    description: str = ''
    weight: float = 1.0
    hours: Hours = Field(default_factory=Hours)
    lo_ids: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)


class Module(BaseModel):
    id: str
    n: int
    title: str
    weight: float = 0.0
    lk_share: float = 0.33
    srs_share: float = 0.2
    lb_hours: int = 0
    hours: Hours = Field(default_factory=Hours)
    control: str = 'Тест'
    expert_id: str | None = None
    review_status: str = 'not_started'
    accepted_items: list[str] = Field(default_factory=list)  # элементы, принятые экспертом по одному (FR-49)
    manual_topics: bool = False  # часы тем заданы методистом вручную, солвер их не перераспределяет (FR-17)
    topics: list[Topic] = Field(default_factory=list)


class CalendarWeek(BaseModel):
    week: int
    hours: int
    days: int
    lk: int = 0
    pr: int = 0
    lb: int = 0
    srs: int = 0
    ia: int = 0
    items: list[str] = Field(default_factory=list)


class CalendarOption(BaseModel):
    id: str
    title: str
    weeks: int
    hours_per_day: int
    days_per_week: int


class Calendar(BaseModel):
    weeks: int = 0
    work_days: int = 0
    hours_per_day: int = 0
    days_per_week: int = 5
    hours_per_week: int = 0
    sessions: int = 0
    session_hours: int = 0
    requested_weeks: float | None = None
    conflict: str = ''
    options: list[CalendarOption] = Field(default_factory=list)
    chosen_option: str | None = None
    schedule: list[CalendarWeek] = Field(default_factory=list)


class Source(BaseModel):
    id: str
    kind: Literal['book', 'doc', 'law', 'ps', 'url']
    bibl: str
    url: str = ''
    confirmed: bool = False
    checked_at: str = ''


class Question_(BaseModel):
    """Вопрос теста с ключом и привязкой к РО."""

    id: str
    assessment_id: str
    module_id: str | None = None
    stem: str
    options: list[str]
    key: int
    lo_ids: list[str] = Field(default_factory=list)
    difficulty: int = 2
    # F12: происхождение элемента — честная подача: llm (модель), template (шаблонный резерв), repaired (исправлен repair)
    origin: Literal['llm', 'template', 'repaired'] = 'template'


class Criterion(BaseModel):
    text: str
    points: int


class Task(BaseModel):
    id: str
    assessment_id: str
    module_id: str | None = None
    topic_id: str | None = None
    title: str
    statement: str
    expected_result: str = ''
    criteria: list[Criterion] = Field(default_factory=list)
    lo_ids: list[str] = Field(default_factory=list)
    origin: Literal['llm', 'template', 'repaired'] = 'template'  # F12: происхождение элемента


class Slide(BaseModel):
    id: str
    n: int
    title: str
    bullets: list[str] = Field(default_factory=list)
    notes: str = ''


def fit_plan(plan: list[dict[str, Any]], duration: int) -> list[dict[str, Any]]:
    """Хронометраж плана лекции равен её длительности (FR-28): минуты масштабируются, шаг 5 мин, остаток — наибольшим долям."""
    items = [p for p in plan if isinstance(p, dict)]
    if not items or duration <= 0:
        return plan
    total = sum(max(1, int(p.get('min') or 1)) for p in items)
    if total == duration:
        return plan
    units, step = duration // 5, 5
    if units < len(items):
        units, step = duration, 1
    raw = [max(1, int(p.get('min') or 1)) * units / total for p in items]
    base = [max(1, int(r)) for r in raw]
    while sum(base) > units and max(base) > 1:
        base[base.index(max(base))] -= 1
    order = sorted(range(len(raw)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    i = 0
    while sum(base) < units:
        base[order[i % len(order)]] += 1
        i += 1
    out = [{**p, 'min': b * step} for p, b in zip(items, base, strict=True)]
    out[-1]['min'] += duration - sum(x['min'] for x in out)
    return out


class Lecture(BaseModel):
    id: str
    topic_id: str
    module_id: str
    title: str
    duration_min: int = 90
    plan: list[dict[str, Any]] = Field(default_factory=list)  # [{min, text}]
    code_examples: list[str] = Field(default_factory=list)
    slides: list[Slide] = Field(default_factory=list)
    origin: Literal['llm', 'template', 'repaired'] = 'template'  # F12: происхождение элемента


class Assessment(BaseModel):
    id: str
    module_id: str | None = None
    kind: Literal['test', 'seminar', 'project', 'final', 'interview']
    title: str


class ModuleProgram(BaseModel):
    """Рабочая программа модуля."""

    module_id: str
    annotation: str = ''
    content: list[dict[str, str]] = Field(default_factory=list)  # [{topic_id, text}]
    control_questions: list[str] = Field(default_factory=list)


class Kit(BaseModel):
    module_programs: list[ModuleProgram] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    questions: list[Question_] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    lectures: list[Lecture] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)  # разделы шаблона АЦР
    final_assessment: dict[str, Any] = Field(default_factory=dict)
    report_requirements: list[str] = Field(default_factory=list)
    drafts: list[str] = Field(default_factory=list)  # модули, собранные по шаблону без ответа модели
    judge: dict[str, list[str]] = Field(default_factory=dict)  # замечания судьи по смысловым правилам


class RuleResult(BaseModel):
    id: str
    title: str
    check: int | None  # номер блокирующей проверки 1–10, None — предупреждение
    kind: Literal['code', 'llm']
    status: Literal['pass', 'warn', 'fail', 'skip']
    messages: list[str] = Field(default_factory=list)
    nodes: list[str] = Field(default_factory=list)
    owner: str = 'методист'


class Report(BaseModel):
    stage: Literal['skeleton', 'kit'] = 'skeleton'
    rules: list[RuleResult] = Field(default_factory=list)
    blocking_passed: int = 0
    blocking_total: int = 10
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)  # значения, принятые агентом (FR-13)


class Decision(BaseModel):
    rule_id: str
    node: str = ''  # решение принимается по узлу: у одного правила может быть несколько пунктов «!» (FR-22)
    proposal: str = ''
    decision: Literal['accept', 'keep']
    actor: str
    at: str


class Comment(BaseModel):
    id: str
    module_id: str
    node_id: str = ''
    author: str
    text: str
    agent_proposal: str = ''
    new_text: str = ''
    affected: list[str] = Field(default_factory=list)  # что пересоберётся по графу (FR-41)
    status: Literal['open', 'answered', 'proposed', 'applied'] = 'open'  # proposed — ждёт подтверждения эксперта (FR-48)
    answer: str = ''
    at: str = ''


class Approval(BaseModel):
    stage: Literal['skeleton', 'module', 'program']
    actor: str
    decision: Literal['approve', 'return']
    comment: str = ''
    module_id: str | None = None
    score: int | None = None  # оценка модуля экспертом 1–5 (качество комплекта, FR-50)
    at: str


class Usage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0
    calls: int = 0
    by_skill: dict[str, dict[str, float]] = Field(default_factory=dict)


class StepError(BaseModel):
    """Отказ шага конвейера: что упало, где и какая резервная генерация его заменила."""

    step: str  # intake | skeleton | kit | pipeline
    skill: str = ''
    module: str = ''  # id модуля, если отказ касается одного модуля
    error: str  # тип и текст исключения (без ключей и текстов запросов)
    fallback: str = ''  # что использовано вместо: шаблон, библиотека, эвристика
    at: str = ''


class ReferenceInfo(BaseModel):
    name: str
    chars: int = 0
    structure: list[str] = Field(default_factory=list)
    hours_issues: list[str] = Field(default_factory=list)
    text_sample: str = ''


class ProgramDoc(BaseModel):
    """Состояние программы целиком. Хранится в JSON, версия растёт с каждой правкой."""

    id: str
    org_id: str = 'acr'
    status: Status = Status.DRAFT
    version: int = 1
    mode: Literal['interactive', 'auto'] = 'interactive'
    request: str
    references: list[ReferenceInfo] = Field(default_factory=list)
    norm_mode: Literal['gos', 'org'] = 'gos'
    org_fragments: list[dict[str, Any]] = Field(default_factory=list)  # фрагменты документов организации для генерации (FR-08)
    norm_fragments: list[dict[str, Any]] = Field(default_factory=list)  # выдержки НПА и ФГОС из нормативной базы знаний
    params: Params = Field(default_factory=Params)
    assumptions: list[Assumption] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    type: ProgramType | None = None
    template: str = ''
    issued_document: str = ''
    norm_base: list[Source] = Field(default_factory=list)
    profstandard: ProfStandard | None = None
    title: str = ''
    volume_h: int = 0
    goal: str = ''
    competencies: list[Competency] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    final_assessment: FinalAssessment = Field(default_factory=FinalAssessment)
    calendar: Calendar = Field(default_factory=Calendar)
    min_practice_hours: int = 0
    sources: list[Source] = Field(default_factory=list)
    kit: Kit = Field(default_factory=Kit)
    report: Report | None = None
    decisions: list[Decision] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    agent_notes: list[str] = Field(default_factory=list)
    step_errors: list[StepError] = Field(default_factory=list)  # структурный журнал отказов навыков (резервная генерация)
    usage: Usage = Field(default_factory=Usage)
    timing_s: dict[str, float] = Field(default_factory=dict)
    progress: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ''
    updated_at: str = ''
    # Архив методиста (SPEC-SVC-18…21): признак поверх статуса маршрута — возврат из архива восстанавливает программу как была
    archived_at: str = ''
    archived_by: str = ''

    # --- Навигация по графу ---
    def all_outcomes(self) -> list[LearningOutcome]:
        return [lo for c in self.competencies for i in c.indicators for lo in i.outcomes]

    def all_topics(self) -> list[Topic]:
        return [t for m in self.modules for t in m.topics]

    def module_by_id(self, module_id: str) -> Module | None:
        return next((m for m in self.modules if m.id == module_id), None)

    def fit_lecture_plans(self) -> None:
        for lec in self.kit.lectures:
            lec.plan = fit_plan(lec.plan, lec.duration_min)

    def totals(self) -> Hours:
        tot = Hours()
        for m in self.modules:
            for k in ('total', *KINDS):
                setattr(tot, k, getattr(tot, k) + getattr(m.hours, k))
        return tot
