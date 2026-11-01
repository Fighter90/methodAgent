"""Навык content: содержание одного модуля по утверждённому каркасу (FR-25…FR-29).

Модули генерируются параллельно (семафор слоя моделей). Если модель недоступна,
элемент собирается по шаблону из каркаса и помечается для доработки экспертом —
комплект остаётся полным и согласованным.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import re

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.kb.registry import tools
from app.llm.client import MODEL_DATA_ERRORS, CallStats, LLMUnavailable, get_llm
from app.programs.schemas import (
    Criterion,
    LearningOutcome,
    Lecture,
    Module,
    ModuleProgram,
    ProgramDoc,
    ProgramType,
    Question_,
    Slide,
    StepError,
    Task,
)
from app.skills.base import skill

logger = logging.getLogger(__name__)


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


class SlideDetailLLM(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    notes: str = ''


class LectureSlidesLLM(BaseModel):
    slides: list[SlideDetailLLM] = Field(default_factory=list)


# Второй проход по лекции (SPEC-CONTENT-16): подробные слайды отдельным вызовом, чтобы основной ответ модуля
# (тест, задания, программа) не обрезался по лимиту токенов. Сбой прохода не портит комплект: остаются слайды
# первого ответа, отказ не считается деградацией.
SLIDES_INSTRUCTION = """Ты — опытный преподаватель и методист. Подготовь содержательные слайды ОДНОЙ лекции, а не шаблон.
Логика: цель и план занятия → ключевые понятия с определениями → как это работает (шаги, механизм) →
пример из работы аудитории программы → типичные ошибки и как их избежать → мини-задание или вопрос для обсуждения → итоги.
Требования:
- ровно n_slides слайдов; заголовок слайда — конкретный, по теме (не «Введение», не «Итоги» без сути);
- на КАЖДОМ слайде от 3 до 5 пунктов (bullets — массив из 3–5 строк), каждый пункт в формате «Тезис — пояснение»:
  тезис до 6 слов, длинное тире, затем 1–2 предложения пояснения с конкретикой (команда, инструмент, параметр, число, пример);
  длина пункта 80–220 знаков; слайд с одним или двумя пунктами — ошибка;
- notes — заметки докладчика 50–90 слов: что сказать, пример из практики аудитории, вопрос слушателям; notes не пустые;
- только факты по теме и РО; без выдуманных команд, ссылок, статистики и сервисов, недоступных в России;
- код в пунктах — коротко, в кавычках-ёлочках, без многострочных листингов;
- внутри текста не используй символ двойной кавычки и обратную косую черту: цитаты и код — только в «ёлочках»; каждый пункт — одна строка без переносов.
Пример одного слайда (формат, не содержание):
{"title": "Слои образа и кэш сборки", "bullets": ["Образ из слоёв — каждая инструкция Dockerfile создаёт слой, неизменённые слои берутся из кэша, поэтому сборка после правки кода идёт секунды, а не минуты.", "Порядок инструкций — сначала копируют файл зависимостей и ставят пакеты, потом код: так правка кода не сбрасывает кэш установки.", "Размер образа — многоэтапная сборка оставляет в финальном образе только артефакт, например 80 МБ вместо 900 МБ с компилятором."], "notes": "Покажите вывод «docker build» дважды подряд и обратите внимание, какие шаги взяты из кэша. Спросите слушателей, сколько минут у них сейчас занимает сборка сервиса и что в Dockerfile стоит выше: копирование кода или установка зависимостей. Предложите переставить строки и пересобрать."}
Верни только JSON: {"slides": [ ...n_slides объектов в формате примера... ]}"""


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
    interview: list[str] = Field(default_factory=list)


class ModuleContent(BaseModel):
    program: ModuleProgram
    questions: list[Question_]
    tasks: list[Task]
    lectures: list[Lecture]
    sources: list[str]
    source: str
    interview: list[str] = Field(default_factory=list)


def _module_los(doc: ProgramDoc, m: Module) -> list[LearningOutcome]:
    ids = {lo_id for t in m.topics for lo_id in t.lo_ids}
    return [lo for lo in doc.all_outcomes() if lo.id in ids]


def _relevant_tools(doc: ProgramDoc, m: Module) -> dict[str, str]:
    """Версии только тех инструментов, что встречаются в программе: иначе модель тянет в тесты лишнее."""
    text = ' '.join([doc.title, doc.params.direction, m.title, *(t.title + ' ' + t.description for t in m.topics)]).lower()
    aliases = {'scikit-learn': 'sklearn', 'postgresql': 'sql', 'kubernetes': 'k8s', 'ansible-core': 'ansible', 'gitlab-ci': 'ci/cd'}
    return {k: v for k, v in tools()['current'].items() if k in text or aliases.get(k, '#') in text or (k == 'python' and 'python' in doc.title.lower())}


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
            'tool_versions_2026': _relevant_tools(doc, m),
            # Режим «документы организации»: требования положений и шаблонов учитываются, источник — по имени (FR-08)
            'org_documents': doc.org_fragments[:4],
            # Выдержки НПА и ФГОС из нормативной базы: требования к структуре, срокам, нагрузке детей, ДОТ
            'norm_documents': [{'act': d['name'], 'text': d['text']} for d in doc.norm_fragments[:3]],
            'question_rules': 'Вопросы теста — только по темам и РО этого модуля и на уровне аудитории; не упоминать инструменты, которых нет в темах; дистракторы правдоподобные, без абсурдных вариантов. '
            'Не упоминай сервисы, недоступные в России (' + ', '.join(tools().get('ai_services_blocked', [])) + '), нигде, даже в неверных вариантах ответа.',
            'note': instruction_extra
            or ('Стажировка: задания — практические задания на рабочем месте под руководством наставника. '
                'interview — 3–5 разных вопросов собеседования с руководителем стажировки по темам модуля: '
                'про конкретные действия, инструменты, артефакты и разбор проблем, без шаблона «расскажите, какие задачи».' if internship else ''),
        }
        try:
            data: ModuleContentLLM = await llm.complete_json(
                skill='content',
                system=spec.instruction,
                user=json.dumps(payload, ensure_ascii=False),
                schema=ModuleContentLLM,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens if need_slides else min(spec.max_tokens, 4500),
                stats=stats,
                partial_ok=True,  # недостающие вопросы, задания и лекции _from_llm добирает по шаблону
            )
        except LLMUnavailable as exc:
            # Модель не ответила после всех повторов и резерва (или лимит/бюджет): шаблон из каркаса
            logger.warning('content program=%s module=%s: резервная генерация (%s)', doc.id, m.id, str(exc)[:200])
            if stats is not None:
                stats.fallback('content', exc, 'шаблон из каркаса', module=m.id)
            return fallback(doc, m, los, n_questions, test_id, slide_topics)
        data = scrub_blocked(data)
        data = await _top_up(doc, m, data, payload, spec, n_questions, internship, stats)
        try:
            content = _from_llm(doc, m, los, data, n_questions, test_id, slide_topics)
        except MODEL_DATA_ERRORS as exc:
            # Ответ прошёл схему, но не лёг в каркас: это дефект разбора — трассировка в журнал
            logger.exception('content program=%s module=%s: ответ модели не разобран, резервная генерация', doc.id, m.id)
            if stats is not None:
                stats.fallback('content', exc, 'шаблон из каркаса', module=m.id)
        else:
            if content.lectures and get_settings().llm_slides_detail:
                content.lectures = list(await asyncio.gather(*(_detail_lecture(doc, m, los, lec, stats) for lec in content.lectures)))
            return content
    return fallback(doc, m, los, n_questions, test_id, slide_topics)


async def _top_up(
    doc: ProgramDoc, m: Module, data: ModuleContentLLM, payload: dict, spec, n_questions: int, internship: bool, stats: CallStats | None,
) -> ModuleContentLLM:
    """SPEC-CONTENT-18: модель недодала вопросы теста или задания тем с практикой — один повторный запрос только за
    недостающим; шаблон добирает лишь то, чего не дал и повтор. Отказ повтора не считается деградацией сам по себе."""
    missing_q = max(0, n_questions - len(data.questions))
    covered = {t.topic for t in data.tasks}
    missing_t = [t.n for t in m.topics if ((t.hours.pr + t.hours.lb > 0) or internship) and t.n not in covered]
    if not missing_q and not missing_t:
        return data
    ask = {**payload, 'missing': {'questions': missing_q, 'tasks_for_topics': missing_t},
           'existing_questions': [q.stem for q in data.questions],
           'note': 'Повторный запрос: верни ТОЛЬКО недостающее — ровно missing.questions новых вопросов теста (не повторяй existing_questions) '
                   'и по одному заданию семинара для каждой темы из missing.tasks_for_topics. Остальные поля оставь пустыми.'}
    try:
        extra: ModuleContentLLM = await get_llm().complete_json(
            skill='content', system=spec.instruction, user=json.dumps(ask, ensure_ascii=False), schema=ModuleContentLLM,
            temperature=spec.temperature, max_tokens=min(spec.max_tokens, 3000), stats=stats, partial_ok=True,
        )
    except (LLMUnavailable, *MODEL_DATA_ERRORS) as exc:
        logger.warning('content program=%s module=%s: повтор за недостающим не ответил, добор шаблоном (%s)', doc.id, m.id, str(exc)[:200])
        return data
    extra = scrub_blocked(extra)
    data.questions += extra.questions[:missing_q]
    data.tasks += [t for t in extra.tasks if t.topic in missing_t][: len(missing_t)]
    return data


def slide_count(duration_min: int) -> int:
    """Число подробных слайдов по длительности лекции: 9 на 90 минут, от 6 до 12."""
    return max(6, min(12, round(duration_min / 90 * 9)))


async def _detail_lecture(doc: ProgramDoc, m: Module, los: list[LearningOutcome], lec: Lecture, stats: CallStats | None) -> Lecture:
    """Подробные слайды лекции вторым вызовом; при отказе или скудном ответе лекция остаётся прежней (SPEC-CONTENT-16)."""
    topic = next((t for t in m.topics if t.id == lec.topic_id), None)
    if topic is None:
        return lec
    n = slide_count(lec.duration_min)
    payload = {
        'program': doc.title, 'program_type': doc.template,
        'audience': f'{doc.params.audience}; входной уровень: {doc.params.entry_level}',
        'module': f'Модуль {m.n}. {m.title}',
        'topic': {'n': topic.n, 'title': topic.title, 'description': topic.description},
        'outcomes': [f'{lo.code}: {lo.text}' for lo in los if lo.id in topic.lo_ids],
        'plan': lec.plan, 'code_example': (lec.code_examples or [''])[0][:600],
        'draft_titles': [sl.title for sl in lec.slides], 'n_slides': n,
        'blocked_services': tools().get('ai_services_blocked', []),
    }
    try:
        res = await get_llm().complete_json(
            skill='content', system=SLIDES_INSTRUCTION, user=json.dumps(payload, ensure_ascii=False),
            schema=LectureSlidesLLM, temperature=0.5, max_tokens=4500, stats=stats, partial_ok=True,
        )
    except (LLMUnavailable, *MODEL_DATA_ERRORS) as exc:
        logger.warning('content program=%s lecture=%s: подробные слайды не получены, остаются слайды модуля (%s)', doc.id, lec.id, str(exc)[:200])
        return lec
    raw = getattr(res, 'slides', None) or []
    good = [sl for sl in raw if isinstance(sl, SlideDetailLLM) and sl.title.strip() and sum(1 for b in sl.bullets if len(b.strip()) >= 20) >= 2]
    if len(good) < 4:
        return lec
    rx = _blocked_rx()
    clean = (lambda x: rx.sub('зарубежный сервис', x)) if rx is not None else (lambda x: x)  # noqa: E731
    slides = [
        Slide(id=f'sl{topic.n}.{j}', n=j, title=clean(sl.title.strip())[:120],
              bullets=[clean(b.strip()) for b in sl.bullets if b.strip()][:5], notes=clean(sl.notes.strip())[:1200])
        for j, sl in enumerate(good[:12], start=1)
    ]
    return lec.model_copy(update={'slides': slides})


def _trivial_code(code: str) -> bool:
    """Пример без логики: только print() строковых литералов (или пусто). Такой пример ничего не показывает — не берём."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False  # синтаксис проверит песочница (V-24)

    def _literal(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str)
        return isinstance(node, ast.JoinedStr) and not any(isinstance(v, ast.FormattedValue) for v in node.values)

    for st in tree.body:
        call = st.value if isinstance(st, ast.Expr) else None
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'print'
                and all(_literal(a) for a in call.args)):
            return False
    return True


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
        if not 0 <= q.key < len(q.options):
            # Ключ вне диапазона — дефект вопроса (F09): нулём не подменяется, а остаётся как есть,
            # чтобы его видели V-19 и repair; методисту пишется сообщение в step_errors
            doc.step_errors.append(StepError(
                step='kit', skill='content', module=m.id,
                error=f'Вопрос q{m.n}.{i}: ключ ответа ({q.key}) вне диапазона из {len(q.options)} вариантов',
                fallback='вопрос оставлен с дефектом для проверки V-19 и repair, нужна вычитка эксперта',
            ))
        questions.append(
            Question_(
                id=f'q{m.n}.{i}', assessment_id=test_id, module_id=m.id, stem=q.stem.strip(),
                options=[o.strip() for o in q.options], key=q.key, lo_ids=_lo_ids(q.lo, los, default_lo),
                origin='llm',
            )
        )
    if len(questions) < n_questions:
        extra = fallback(doc, m, los, n_questions, test_id, slide_topics).questions
        added = extra[len(questions) : n_questions]
        for q in added:
            q.origin = 'template'  # F12: добор шаблоном помечается честно
        questions += added
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
                lo_ids=_lo_ids(t.lo, los, topic.lo_ids if topic else []), origin='llm',
            )
        )
    if not tasks:
        for t in fallback(doc, m, los, n_questions, test_id, slide_topics).tasks:
            t.origin = 'template'
            tasks.append(t)
    lectures: list[Lecture] = []
    lec_by_topic = {lec.topic: lec for lec in data.lectures}
    for t in m.topics:
        if t.id not in slide_topics:
            continue
        lec = lec_by_topic.get(t.n)
        if lec is None or not lec.slides:
            lectures.append(_fallback_lecture(m, t, los))
            continue
        slides = [Slide(id=f'sl{t.n}.{j}', n=j, title=s.title, bullets=s.bullets[:6]) for j, s in enumerate(lec.slides[:8], start=1)]
        plan = [{'min': int(p.get('min', 10) or 10), 'text': str(p.get('text', ''))} for p in lec.plan if isinstance(p, dict)]
        lectures.append(
            Lecture(
                id=f'lec{t.n}', topic_id=t.id, module_id=m.id, title=t.title, duration_min=max(45, t.hours.lk * 45),
                plan=plan or _default_plan(t.title), code_examples=[lec.code] if lec.code and not _trivial_code(lec.code) else [], slides=slides,
                origin='llm',
            )
        )
    interview = [q.strip() for q in data.interview if len(q.strip()) > 15][:6]
    return ModuleContent(program=program, questions=questions, tasks=tasks, lectures=lectures, sources=data.sources[:3], source='llm', interview=interview)


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


def _fallback_lecture(m: Module, t, los: list[LearningOutcome] | tuple = ()) -> Lecture:
    """Шаблонная лекция без модели: пять слайдов из каркаса — цель по РО темы, понятия из описания, план по минутам,
    практика и итоги в формате «Тезис — пояснение» (SPEC-CONTENT-17). Черновик для эксперта, без выдуманных фактов."""
    plan = _default_plan(t.title)
    outcomes = [lo for lo in los if lo.id in (t.lo_ids or [])]
    goal = outcomes[0].text if outcomes else (t.description or t.title)
    parts = [p.strip(' .') for p in re.split(r'[,;.]', t.description or '') if len(p.strip()) > 2][:4] or [t.title]
    lk = t.hours.lk or 2
    slides = [
        Slide(id=f'sl{t.n}.1', n=1, title=t.title, bullets=[
            f'Модуль {m.n}. {m.title} — тема {t.n}, лекция {lk} ак. ч',
            f'Цель занятия — {goal}',
            'Результат — ' + ('; '.join(f'{lo.code}: {lo.text}' for lo in outcomes) or f'слушатели применяют тему «{t.title}» в своих задачах'),
        ], notes=f'Откройте занятие вопросом к слушателям: где в их работе встречается «{t.title}». Назовите цель и результат.'),
        Slide(id=f'sl{t.n}.2', n=2, title='Ключевые понятия', bullets=[
            f'{part} — определение и пример из практики слушателей разбираются на занятии' for part in parts
        ], notes='Дайте определение каждому понятию и сразу покажите короткий пример из рабочих задач аудитории.'),
        Slide(id=f'sl{t.n}.3', n=3, title='План занятия', bullets=[f'{p["min"]} мин — {p["text"]}' for p in plan],
              notes='Покажите, сколько времени займёт каждый блок, и где будет практика.'),
        Slide(id=f'sl{t.n}.4', n=4, title=f'Практика: {t.title}', bullets=[
            'Разбор у доски — преподаватель решает типовую задачу по шагам и проговаривает каждое решение',
            f'Самостоятельно — слушатели повторяют решение на своих данных: {goal}',
            'Проверка — сверяем результат с критериями и обсуждаем типичные ошибки',
        ], notes='Дайте задачу, близкую к работе слушателей. Пройдите по рядам, соберите типичные ошибки для итогов.'),
        Slide(id=f'sl{t.n}.5', n=5, title='Итоги', bullets=[
            'Что проверим — ' + (', '.join(lo.code for lo in outcomes) or 'результаты обучения темы') + ': вопросы теста и задание семинара',
            f'Повторить — {", ".join(parts)}',
            'Вопрос для обсуждения — где вы примените это на следующей неделе?',
        ], notes='Подведите итог по цели занятия, ответьте на вопросы, назовите задание к следующему занятию.'),
    ]
    return Lecture(
        id=f'lec{t.n}', topic_id=t.id, module_id=m.id, title=t.title, duration_min=max(45, t.hours.lk * 45),
        plan=plan, slides=slides, origin='template',
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
    # Дистракторы — реальные РО других модулей: правдоподобно, но к этой теме не относится
    foreign = [lo.text for lo in doc.all_outcomes() if lo.id not in {x.id for x in los}]
    foreign += [t.description or t.title for mm in doc.modules if mm.id != m.id for t in mm.topics]
    foreign = list(dict.fromkeys(foreign)) or ['Настраивает оборудование локальной сети', 'Составляет бухгалтерский баланс', 'Пишет эссе по истории']
    stems = ('Какой результат формирует тема «{t}»?', 'Что слушатель умеет после темы «{t}»?', 'Какое действие относится к теме «{t}»?')
    lo_by_id = {lo.id: lo for lo in los}
    for i in range(n_questions):
        topic = m.topics[i % len(m.topics)]
        topic_los = [lo_by_id[x] for x in topic.lo_ids if x in lo_by_id] or los
        lo = topic_los[(i // len(m.topics)) % len(topic_los)] if topic_los else None
        correct = lo.text if lo else topic.description or topic.title
        distract = [f for f in foreign if f != correct]
        k0 = (i * 3) % max(1, len(distract))
        options = [correct, *[distract[(k0 + j) % len(distract)] for j in range(3)]]
        options = list(dict.fromkeys(options))
        while len(options) < 4:
            options.append(f'Не относится к модулю «{m.title}» (вариант {len(options)})')
        key = i % 4
        options[0], options[key] = options[key], options[0]
        questions.append(
            Question_(
                id=f'q{m.n}.{i + 1}', assessment_id=test_id, module_id=m.id,
                stem=stems[(i // max(1, len(m.topics))) % len(stems)].format(t=topic.title),
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
    lectures = [_fallback_lecture(m, t, los) for t in m.topics if t.id in slide_topics]
    return ModuleContent(program=program, questions=questions, tasks=tasks, lectures=lectures, sources=[], source='template')



def _blocked_rx() -> re.Pattern[str] | None:
    names = tools().get('ai_services_blocked', [])
    return re.compile(r'\b(' + '|'.join(re.escape(n) for n in names) + r')\b(\s*\([^)]*\))?', re.I) if names else None


def scrub_blocked(data: ModuleContentLLM) -> ModuleContentLLM:
    """Сервисы, недоступные в России, не попадают в комплект даже как неверные варианты теста.

    Вопрос с таким сервисом отбрасывается (его место займёт шаблонный), в остальном тексте сервис
    заменяется словами «зарубежный сервис».
    """
    rx = _blocked_rx()
    if rx is None:
        return data
    # Замена в вариантах может дать второй верный ответ («какой сервис доступен в России?») — вопрос отбрасывается целиком
    kept = [q for q in data.questions if not rx.search(' '.join([q.stem, *q.options]))]
    data.questions = kept
    raw = data.model_dump()
    raw.pop('questions')

    def walk(x):  # noqa: ANN001, ANN202
        if isinstance(x, str):
            return rx.sub('зарубежный сервис', x)
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x

    cleaned = ModuleContentLLM.model_validate({**walk(raw), 'questions': [q.model_dump() for q in kept]})
    return cleaned
