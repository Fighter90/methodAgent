"""Оркестратор (навык workflow): конечный автомат программы и запуск навыков.

draft → questions → skeleton → skeleton_approved → generating → kit_ready →
on_review → on_approval → approved (возвраты: returned).
Генерация содержания недоступна, пока каркас не утверждён (FR-23).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from app.agent.sections import build_sections
from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import Conflict, NotFound
from app.kb.registry import literature_for, match_source
from app.llm.client import CallStats, get_llm
from app.programs.schemas import (
    Approval,
    Assessment,
    Assumption,
    Calendar,
    CalendarOption,
    CalendarWeek,
    Comment,
    Criterion,
    Decision,
    FinalAssessment,
    Hours,
    Kit,
    Module,
    ProgramDoc,
    ProgramType,
    ReferenceInfo,
    Source,
    Status,
    Task,
    Topic,
)
from app.skills.clarify import run as clarify
from app.skills.classify import run as classify
from app.skills.content import run as content
from app.skills.intake import run as intake
from app.skills.skeleton import run as skeleton
from app.solver.calendar import CalendarOut, apply_option, plan_calendar
from app.solver.hours import (
    KINDS,
    HoursRow,
    ModuleIn,
    TopicIn,
    largest_remainder,
    solve,
)
from app.validation.judge import judge
from app.validation.repair import repair
from app.validation.report import build_report

logger = logging.getLogger(__name__)

ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop(_: dict[str, Any]) -> None:
    return None


def _stats_to_usage(doc: ProgramDoc, stats: CallStats) -> None:
    u = doc.usage
    u.tokens_in += stats.tokens_in
    u.tokens_out += stats.tokens_out
    u.cost_rub = round(u.cost_rub + stats.cost_rub, 4)
    u.calls += stats.calls
    for skill_name, s in stats.by_skill.items():
        cur = u.by_skill.setdefault(skill_name, {'tokens_in': 0, 'tokens_out': 0, 'cost_rub': 0.0, 'calls': 0})
        for k, v in s.items():
            cur[k] = round(cur.get(k, 0) + v, 4)


# --------------------------------------------------------------------------- шаг 1–2
async def intake_step(doc: ProgramDoc, references: list[ReferenceInfo], ref_text: str) -> None:
    """Разбор запроса, тип программы, нормативная база, вопросы."""
    stats = CallStats()
    started = time.monotonic()
    doc.references = references
    params, _used = await intake.run(doc.request, ref_text, stats)
    doc.params = params
    if references:
        params.reference_used = True
        for ref in references:
            if ref.hours_issues:
                doc.agent_notes.append(
                    f'В референсе «{ref.name}» таблицы часов не сходятся ({len(ref.hours_issues)} расх.): '
                    + '; '.join(ref.hours_issues[:3]) + '. Ошибки в каркас не переносятся.'
                )
            else:
                doc.agent_notes.append(f'Таблицы часов в референсе «{ref.name}» проверены: расхождений нет.')
        doc.agent_notes.append('Из приложенной программы беру структуру разделов, текст не переношу.')
    elif params.reference_used:
        doc.agent_notes.append('Запрос ссылается на образец, но файл не приложен — структура взята из шаблона АЦР.')
    if params.reference_used and doc.params.program_type == ProgramType.DPP_PK_INTERNSHIP and not references:
        doc.agent_notes.append(
            'В образце стажировки АЦР «Бизнес и системный анализ» (248 ч) итоговая строка учебного плана не сходится '
            'с остальными строками (ПР 66, ЛБ 6, СРС 174 ч при модуле 0/0/0/246 ч) — ошибка не перенесена: все часы модулей учтены как СРС.'
        )
    _classify(doc)
    doc.questions = clarify.run(doc.params)
    _stats_to_usage(doc, stats)
    doc.timing_s['intake'] = round(time.monotonic() - started, 2)


def _classify(doc: ProgramDoc) -> None:
    res = classify.run(doc.request, doc.params)
    doc.type = res.program_type
    doc.template = res.template
    doc.issued_document = res.issued_document
    doc.norm_base = res.norm_base
    doc.profstandard = res.profstandard
    if res.message and res.program_type:
        doc.agent_notes = [n for n in doc.agent_notes if not n.startswith('Это ')]
        doc.agent_notes.insert(0, res.message)


def answer_questions(doc: ProgramDoc, answers: dict[str, str]) -> None:
    if doc.status != Status.QUESTIONS:
        raise Conflict('Вопросов к этой программе нет', code='NO_QUESTIONS')
    doc.assumptions += clarify.apply_answers(doc.params, doc.questions, answers)
    _classify(doc)


def fill_defaults(doc: ProgramDoc) -> None:
    """Режим auto: пустые поля — значениями профиля, с перечнем допущений (FR-62)."""
    if doc.questions:
        doc.assumptions += clarify.fill_defaults(doc.params)
        _classify(doc)


# --------------------------------------------------------------------------- шаг 3
def _final_hours(doc: ProgramDoc) -> int:
    p = doc.params
    if p.final_assessment_hours:
        return p.final_assessment_hours
    v = p.volume_h or 72
    if doc.type == ProgramType.DOOP:
        return 2 if v <= 24 else 4
    return 2 if v <= 36 else 4 if v <= 144 else 6


def _resolve_slide_modules(doc: ProgramDoc) -> None:
    mat = doc.params.materials
    if mat.slides_topic_hint and not mat.slides_modules:
        hint = mat.slides_topic_hint.lower()[:5]
        for m in doc.modules:
            if hint in m.title.lower() or any(hint in t.title.lower() for t in m.topics[:1]):
                mat.slides_modules = [m.n]
                break
    if not mat.slides_modules and not mat.slides_lessons:
        first = next((m for m in doc.modules if m.hours.lk > 0), doc.modules[0] if doc.modules else None)
        if first:
            mat.slides_modules = [first.n]
            doc.assumptions.append(Assumption(field='slides_modules', value=[first.n], source='профиль АЦР: слайды хотя бы для одного модуля'))


def slide_topic_ids(doc: ProgramDoc) -> set[str]:
    """Темы, для которых нужны слайды: модули из запроса или первые занятия ДООП."""
    mat = doc.params.materials
    ids: set[str] = set()
    for m in doc.modules:
        if m.n in mat.slides_modules:
            ids |= {t.id for t in m.topics if t.hours.lk > 0 or doc.type == ProgramType.DOOP}
            if not ids:
                ids |= {t.id for t in m.topics}
    if mat.slides_lessons:
        session = doc.calendar.session_hours or 2
        lessons = set(mat.slides_lessons)
        acc = 0
        for t in doc.all_topics():
            first_lesson = acc // session + 1
            last_lesson = (acc + max(t.hours.total, 1) - 1) // session + 1
            if any(first_lesson <= n <= last_lesson for n in lessons):
                ids.add(t.id)
            acc += t.hours.total
    return ids


def apply_solver(doc: ProgramDoc, modules: list[Module]) -> None:
    p = doc.params
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP or p.no_classroom
    volume = p.volume_h or 72
    final_h = _final_hours(doc)
    min_pr = p.min_practice_hours or (int(volume * p.min_practice_share + 0.999) if p.min_practice_share else 0)
    doc.min_practice_hours = min_pr
    result = solve(
        volume=volume,
        final_hours=final_h,
        modules=[
            ModuleIn(
                title=m.title, weight=m.weight, lk_share=m.lk_share,
                srs_share=0.0 if doc.type == ProgramType.DOOP and not p.distance else m.srs_share,
                lb_hours=m.lb_hours, topics=[TopicIn(t.title, t.weight) for t in m.topics],
            )
            for m in modules
        ],
        internship=internship,
        min_practice_hours=min_pr,
    )
    for m, mo in zip(modules, result.modules, strict=True):
        m.hours = Hours(**mo.hours.as_dict())
        kept = []
        for t, (_title, row) in zip(m.topics, mo.topics, strict=False):
            t.hours = Hours(**row.as_dict())
            kept.append(t)
        dropped = m.topics[len(kept) :]
        if dropped and kept:
            kept[-1].lo_ids = list(dict.fromkeys(kept[-1].lo_ids + [x for t in dropped for x in t.lo_ids]))
        m.topics = kept
        if internship:
            m.control = 'Собеседование с руководителем стажировки'
    doc.modules = modules
    doc.volume_h = volume
    doc.final_assessment = FinalAssessment(form=p.final_assessment_form or 'Зачёт', hours=result.final_hours)
    doc.agent_notes += [n for n in result.notes if n not in doc.agent_notes]


def _schedule_items(doc: ProgramDoc) -> list[tuple[str, int]]:
    items = [(f'Тема {t.n}. {t.title}', t.hours.total) for t in doc.all_topics()]
    items.append((f'Итоговая аттестация: {doc.final_assessment.form}', doc.final_assessment.hours))
    return items


def _to_calendar(c: CalendarOut, chosen: str | None = None) -> Calendar:
    return Calendar(
        weeks=c.weeks, work_days=c.work_days, hours_per_day=c.hours_per_day, days_per_week=c.days_per_week,
        hours_per_week=c.hours_per_week, sessions=c.sessions, session_hours=c.session_hours,
        requested_weeks=c.requested_weeks, conflict=c.conflict,
        options=[CalendarOption(**o.__dict__) for o in c.options], chosen_option=chosen,
        schedule=[CalendarWeek(**w) for w in c.schedule],
    )


def plan_doc_calendar(doc: ProgramDoc) -> None:
    p = doc.params
    hpd = p.max_hours_per_day
    if doc.type == ProgramType.DPP_PK_INTERNSHIP and not hpd:
        hpd = 4
    cal = plan_calendar(
        volume=doc.volume_h,
        requested_weeks=p.duration_weeks,
        hours_per_day=hpd,
        days_per_week=p.days_per_week,
        sessions_per_week=p.sessions_per_week,
        session_hours=p.session_hours,
        items=_schedule_items(doc),
    )
    doc.calendar = _to_calendar(cal)


def choose_calendar_option(doc: ProgramDoc, option_id: str) -> None:
    c = doc.calendar
    out = CalendarOut(
        weeks=c.weeks, work_days=c.work_days, hours_per_day=c.hours_per_day, days_per_week=c.days_per_week,
        hours_per_week=c.hours_per_week, sessions=c.sessions, session_hours=c.session_hours,
        requested_weeks=c.requested_weeks, conflict=c.conflict,
        options=[__import__('app.solver.calendar', fromlist=['CalendarOptionOut']).CalendarOptionOut(**o.model_dump()) for o in c.options],
    )
    out = apply_option(out, option_id, doc.volume_h, _schedule_items(doc))
    doc.calendar = _to_calendar(out, chosen=option_id)


async def skeleton_step(doc: ProgramDoc, comment: str = '') -> None:
    """Каркас ≤ 180 с: структура от модели, часы — солвер, затем проверка V-01…V-27 (каркасные)."""
    if doc.type is None:
        raise Conflict('Сначала ответьте на вопросы: тип программы не определён', code='QUESTIONS_PENDING')
    stats = CallStats()
    started = time.monotonic()
    if doc.norm_mode == 'org' and not any(n.startswith(('Использую документы организации', 'Режим «документы организации»')) for n in doc.agent_notes):
        from app.agent.extras import apply_org_docs

        await apply_org_docs(doc)
    structure = [s for r in doc.references for s in r.structure]
    draft = await skeleton.run(doc.params, doc.type, doc.profstandard, structure, stats, comment)
    if draft.source != 'llm':
        doc.agent_notes.append('Каркас собран по типовой структуре направления (модель недоступна) — проверьте темы.')
    doc.title = _cap((doc.params.title or draft.title).strip())
    doc.goal = draft.goal
    doc.competencies = draft.competencies
    if doc.type == ProgramType.DOOP:
        doc.profstandard = None
        for c in doc.competencies:
            c.ps_code, c.tf_codes = None, []
    apply_solver(doc, draft.modules)
    plan_doc_calendar(doc)
    _resolve_slide_modules(doc)
    _expectation_note(doc)
    doc.report = build_report(doc, 'skeleton')
    doc.status = Status.SKELETON
    _stats_to_usage(doc, stats)
    doc.timing_s['skeleton'] = round(time.monotonic() - started + doc.timing_s.get('intake', 0), 2)


def _expectation_note(doc: ProgramDoc) -> None:
    exp = doc.params.customer_expectation
    if exp and not any('ожидани' in n.lower() for n in doc.agent_notes):
        doc.agent_notes.append(
            f'Ожидание заказчика: «{exp}». За {doc.volume_h} ч слушатели достигают начального уровня по ключевым '
            f'компетенциям; полная подготовка специалиста требует большего объёма и практики. Разрыв стоит согласовать с заказчиком.'
        )


def recompute(doc: ProgramDoc) -> None:
    """Пересчёт после правки часов методистом: темы перераспределяются солвером внутри модуля."""
    for m in doc.modules:
        m.hours.total = m.hours.kinds_sum()
        if m.topics:
            from app.solver.hours import _split_topics

            rows = _split_topics(HoursRow(**m.hours.model_dump()), [TopicIn(t.title, t.weight) for t in m.topics])
            for t, r in zip(m.topics, rows, strict=True):
                t.hours = Hours(**r.as_dict())
    plan_doc_calendar(doc)
    doc.report = build_report(doc, 'skeleton')


def patch_skeleton(doc: ProgramDoc, patch: dict[str, Any]) -> None:
    if doc.status not in (Status.SKELETON, Status.RETURNED):
        raise Conflict('Каркас уже утверждён: используйте точечную правку', code='SKELETON_LOCKED')
    for mp in patch.get('modules', []):
        m = next((x for x in doc.modules if x.id == mp.get('id')), None)
        if m is None:
            raise NotFound(f'Модуль {mp.get("id")} не найден')
        if 'title' in mp:
            m.title = str(mp['title'])[:200]
        for k in KINDS:
            if k in mp.get('hours', {}):
                setattr(m.hours, k, max(0, int(mp['hours'][k])))
        for tp in mp.get('topics', []):
            t = next((x for x in m.topics if x.id == tp.get('id')), None)
            if t and 'title' in tp:
                t.title = str(tp['title'])[:200]
    for cp in patch.get('competencies', []):
        c = next((x for x in doc.competencies if x.id == cp.get('id')), None)
        if c and 'title' in cp:
            c.title = str(cp['title'])[:300]
    for lp in patch.get('outcomes', []):
        lo = next((x for x in doc.all_outcomes() if x.id == lp.get('id')), None)
        if lo and 'text' in lp:
            lo.text = str(lp['text'])[:300]
    if 'goal' in patch:
        doc.goal = str(patch['goal'])[:500]
    if 'final_hours' in patch:
        doc.final_assessment.hours = max(0, int(patch['final_hours']))
    if 'calendar_option' in patch:
        choose_calendar_option(doc, str(patch['calendar_option']))
    recompute(doc)
    if 'calendar_option' in patch:
        choose_calendar_option(doc, str(patch['calendar_option']))
        doc.report = build_report(doc, 'skeleton')


def decide(doc: ProgramDoc, rule_id: str, decision: str, actor: str, node: str = '', proposal: str = '', option_id: str = '') -> None:
    """Решение методиста по пункту «!» (FR-22): принять предложение агента или оставить как есть."""
    if decision == 'accept':
        if rule_id == 'V-22' and node:
            lo = next((x for x in doc.all_outcomes() if x.id == node), None)
            if lo and proposal:
                lo.text = proposal
        if rule_id == 'V-10' and option_id:
            choose_calendar_option(doc, option_id)
    doc.decisions.append(Decision(rule_id=rule_id, proposal=proposal, decision=decision, actor=actor, at=now_iso()))
    doc.report = build_report(doc, 'skeleton')


def approve_skeleton(doc: ProgramDoc, actor: str, *, auto: bool = False) -> None:
    if doc.status not in (Status.SKELETON, Status.RETURNED):
        raise Conflict('Каркас нельзя утвердить в текущем состоянии', code='BAD_STATE')
    report = doc.report or build_report(doc, 'skeleton')
    errors = [r for r in report.rules if r.status == 'fail']
    if auto:
        seen: set[str] = set()
        for p in report.proposals:
            # Из нескольких вариантов одного пункта берём первый; календарь, выбранный заранее, не трогаем
            if p['rule_id'] in seen or (p['rule_id'] == 'V-10' and doc.calendar.chosen_option):
                continue
            seen.add(p['rule_id'])
            if not p.get('decided'):
                decide(doc, p['rule_id'], 'accept', 'auto-approve', p.get('node', ''), p.get('proposal', ''), p.get('option_id', ''))
        report = doc.report or report
        errors = [r for r in report.rules if r.status == 'fail']
    if errors:
        raise Conflict(
            'Есть ошибки ✕ — утвердить каркас нельзя', code='SKELETON_HAS_ERRORS',
            details={'errors': [m for r in errors for m in r.messages][:10]},
        )
    pending = [p for p in report.proposals if not p.get('decided')]
    if pending and not auto:
        raise Conflict('По каждому пункту «!» нужно решение: принять или оставить', code='DECISIONS_PENDING', details={'pending': pending})
    doc.approvals.append(Approval(stage='skeleton', actor=actor, decision='approve', at=now_iso()))
    doc.status = Status.SKELETON_APPROVED


def return_skeleton(doc: ProgramDoc, actor: str, comment: str) -> None:
    if not comment.strip():
        raise Conflict('Без комментария вернуть нельзя', code='COMMENT_REQUIRED')
    doc.approvals.append(Approval(stage='skeleton', actor=actor, decision='return', comment=comment, at=now_iso()))


# --------------------------------------------------------------------------- шаг 5
def _n_questions(doc: ProgramDoc, m: Module) -> int:
    if doc.params.materials.test_questions:
        return 0
    return max(4, min(12, m.hours.total // 3))


def _distribute_final_test(doc: ProgramDoc) -> dict[str, int]:
    n = doc.params.materials.test_questions or 0
    if not n:
        return {}
    weights = [m.hours.total for m in doc.modules]
    parts = largest_remainder(n, weights)
    return {m.id: k for m, k in zip(doc.modules, parts, strict=True)}


async def generate_kit(doc: ProgramDoc, progress: ProgressFn = _noop) -> None:
    """Комплект: модули параллельно, затем разделы шаблона, источники, проверка и repair."""
    if doc.status not in (Status.SKELETON_APPROVED, Status.KIT_READY, Status.GENERATING):
        raise Conflict('Пока каркас не утверждён, содержание не генерируется', code='SKELETON_NOT_APPROVED')
    doc.status = Status.GENERATING
    started = time.monotonic()
    stats = CallStats()
    slide_topics = slide_topic_ids(doc)
    final_split = _distribute_final_test(doc)
    kit = Kit()
    module_state = {m.id: {'n': m.n, 'title': m.title, 'status': 'ждёт', 'parts': ''} for m in doc.modules}
    feed: list[dict[str, str]] = []

    workers = max(4, get_settings().gen_workers)
    gate = asyncio.Semaphore(workers)

    async def _report(extra: str = '') -> None:
        if extra:
            feed.append({'t': time.strftime('%H:%M:%S'), 'text': extra})
        elapsed = time.monotonic() - started
        done = sum(1 for x in module_state.values() if x['status'] == 'готово')
        eta = round(elapsed / done * (len(module_state) - done), 0) if done else None
        await progress({
            'modules': list(module_state.values()), 'feed': feed[-12:], 'workers': workers,
            'usage': {'tokens': stats.tokens_in + stats.tokens_out, 'cost_rub': round(stats.cost_rub, 2), 'by_skill': stats.by_skill},
            'elapsed_s': round(elapsed, 1), 'eta_s': eta, 'done': done, 'total': len(module_state),
        })

    async def _one(m: Module):
        async with gate:
            return await _one_inner(m)

    async def _one_inner(m: Module):
        module_state[m.id]['status'] = 'идёт'
        await _report(f'content · модуль {m.n} «{m.title}»')
        test_id = 'test-final' if final_split else f'test-{m.id}'
        n_q = final_split.get(m.id, 0) if final_split else _n_questions(doc, m)
        res = await content.run(doc, m, n_questions=n_q, test_id=test_id, slide_topics=slide_topics, stats=stats)
        module_state[m.id]['status'] = 'готово'
        module_state[m.id]['parts'] = f'тест {len(res.questions)} · задания {len(res.tasks)} · лекции {len(res.lectures)}'
        await _report(f'готово · модуль {m.n}: {module_state[m.id]["parts"]}')
        return m, res

    results = await asyncio.gather(*(_one(m) for m in doc.modules))
    extra_sources: list[str] = []
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP
    for m, res in results:
        kit.module_programs.append(res.program)
        kit.questions += res.questions
        kit.tasks += res.tasks
        kit.lectures += res.lectures
        extra_sources += res.sources
        if res.source != 'llm':
            kit.drafts.append(m.id)
        if res.questions and not final_split:
            kit.assessments.append(Assessment(id=f'test-{m.id}', module_id=m.id, kind='test', title=f'Тест М{m.n}'))
        if res.tasks:
            kit.assessments.append(
                Assessment(id=f'sem-{m.id}', module_id=m.id, kind='interview' if internship else 'seminar', title=f'{"Стаж." if internship else "Сем."} М{m.n}')
            )
    if final_split:
        kit.assessments.append(Assessment(id='test-final', kind='test', title='Итоговый тест'))
        for i, q in enumerate(kit.questions, start=1):
            q.id = f'qf.{i}'
    # Лекции без слайдов: план для каждой темы с лекционными часами
    planned = {lec.topic_id for lec in kit.lectures}
    from app.skills.content.run import _default_plan

    for m in doc.modules:
        for t in m.topics:
            if t.hours.lk > 0 and t.id not in planned:
                from app.programs.schemas import Lecture

                kit.lectures.append(Lecture(id=f'lec{t.n}', topic_id=t.id, module_id=m.id, title=t.title, duration_min=t.hours.lk * 45, plan=_default_plan(t.title)))
    kit.final_assessment, final_task, report_req = _final_assessment(doc)
    kit.tasks.append(final_task)
    kit.assessments.append(Assessment(id='final', kind='final', title='ИА'))
    kit.report_requirements = report_req
    if internship:
        kit.final_assessment['interview_questions'] = {
            m.title: [f'Расскажите, какие задачи по теме «{t.title}» вы выполнили на стажировке и с каким результатом.' for t in m.topics]
            for m in doc.modules
        }
    doc.kit = kit
    await _fix_examples(doc, stats, _report)
    _sources(doc, extra_sources)
    doc.kit.sections = build_sections(doc)
    await _report('validate · 27 правил')
    doc.report = build_report(doc, 'kit')
    for _attempt in range(2):
        if all(r.status != 'fail' for r in doc.report.rules):
            break
        log = repair(doc, doc.report.rules)
        if log:
            await _report('repair · ' + '; '.join(log[:3]))
        doc.kit.sections = build_sections(doc)
        doc.report = build_report(doc, 'kit')
    if get_settings().llm_judge_enabled and get_llm().enabled:
        await _report('judge · смысловые правила V-21, V-22, V-26, V-27')
        for line in await judge(doc, stats):
            await _report('judge · ' + line[:120])
        doc.report = build_report(doc, 'kit')
    doc.status = Status.KIT_READY
    _stats_to_usage(doc, stats)
    doc.timing_s['kit'] = round(time.monotonic() - started, 2)
    await _report('Комплект собран')


def _final_assessment(doc: ProgramDoc) -> tuple[dict[str, Any], Task, list[str]]:
    form = doc.final_assessment.form or 'Зачёт'
    low = form.lower()
    all_lo = [lo.id for lo in doc.all_outcomes()]
    report_req: list[str] = []
    if 'отч' in low:
        statement = 'Подготовить и защитить отчёт о стажировке: задачи, выполненные работы, артефакты, выводы.'
        report_req = [
            'Титульный лист и сведения о месте стажировки (без персональных данных наставника)',
            'Цели и задачи стажировки, перечень выполненных работ по каждому разделу программы',
            'Артефакты: конфигурации, скрипты, схемы инфраструктуры, ссылки на репозитории',
            'Анализ результатов и выводы, отзыв руководителя стажировки',
            'Объём 10–20 страниц, приложения — по необходимости',
        ]
        criteria = [Criterion(text='Полнота отчёта по всем разделам программы', points=3), Criterion(text='Качество артефактов и их работоспособность', points=3),
                    Criterion(text='Ответы на вопросы комиссии', points=2), Criterion(text='Оформление и соблюдение сроков', points=2)]
    elif 'портфолио' in low:
        statement = 'Собрать портфолио из трёх материалов, созданных с помощью ИИ: план урока, комплект заданий для учеников, проверочная работа с критериями.'
        criteria = [Criterion(text='План урока: цели, этапы, соответствие ФГОС', points=3), Criterion(text='Задания: разные уровни сложности, проверены на ошибки', points=3),
                    Criterion(text='Проверочная работа: ключи и критерии оценивания', points=3), Criterion(text='Соблюдены правила безопасности и защиты персональных данных', points=1)]
    elif 'экзамен' in low:
        statement = 'Экзамен с практическим заданием на стенде. Пример задания: на учебном стенде обнаружить признаки атаки в журналах, закрыть уязвимость и оформить краткий отчёт об инциденте.'
        criteria = [Criterion(text='Задание выполнено на стенде полностью', points=4), Criterion(text='Выбраны корректные средства и настройки', points=3),
                    Criterion(text='Отчёт об инциденте оформлен по шаблону', points=2), Criterion(text='Ответ на теоретический вопрос', points=1)]
    elif 'проект' in low:
        child = doc.type == ProgramType.DOOP
        statement = (
            'Защитить небольшой собственный проект (например, простую игру или чат-бота): показать, как работает программа, и рассказать, как она устроена.'
            if child else 'Выполнить и защитить проект на обезличенных данных: постановка задачи, подготовка данных, анализ, визуализация, выводы и рекомендации.'
        )
        criteria = (
            [Criterion(text='Программа запускается и работает без ошибок', points=3), Criterion(text='В программе есть условия, циклы и переменные', points=3),
             Criterion(text='Ученик понятно объясняет, как устроена программа', points=2), Criterion(text='Есть своя идея или интересная доработка', points=2)]
            if child else
            [Criterion(text='Требования к данным соблюдены: данные обезличены, источник описан', points=2), Criterion(text='Корректность обработки и анализа данных', points=3),
             Criterion(text='Качество визуализации и выводов', points=3), Criterion(text='Защита: ответы на вопросы', points=2)]
        )
    else:
        statement = f'Итоговая аттестация в форме: {form}. Слушатель выполняет комплексное задание по материалам программы.'
        criteria = [Criterion(text='Задание выполнено полностью', points=5), Criterion(text='Ответы на вопросы', points=5)]
    if not report_req:
        if 'проект' in low and doc.type != ProgramType.DOOP:
            report_req = [
                'Постановка задачи и описание исходных данных (данные обезличены, источник указан)',
                'Ход решения: подготовка данных, применённые методы и инструменты',
                'Результаты: таблицы, графики, выводы и рекомендации для заказчика',
                'Презентация для защиты на 5–7 минут и ссылка на файлы проекта',
            ]
        elif 'проект' in low:
            report_req = ['Работающая программа или прототип', 'Короткий рассказ: идея, как устроена программа, что получилось', 'Демонстрация на защите до 5 минут']
        elif 'портфолио' in low:
            report_req = ['Три материала, созданных с помощью ИИ, с указанием сервиса и промпта', 'Проверка каждого материала на ошибки и соответствие ФГОС', 'Краткая рефлексия: что сократило время подготовки и какие риски учтены']
    task = Task(id='final-task', assessment_id='final', title=f'Итоговая аттестация: {form}', statement=statement,
                expected_result='Результат, соответствующий критериям', criteria=criteria, lo_ids=all_lo)
    doc.final_assessment.description = statement
    return {'form': form, 'hours': doc.final_assessment.hours, 'statement': statement, 'criteria': [c.model_dump() for c in criteria]}, task, report_req


def _sources(doc: ProgramDoc, extra: list[str]) -> None:
    text = ' '.join([doc.title, doc.params.direction, ' '.join(m.title for m in doc.modules)])
    sources = list(doc.norm_base)
    if doc.profstandard:
        sources.append(Source(id=f'ps-{doc.profstandard.code}', kind='ps', bibl=f'Профессиональный стандарт {doc.profstandard.code} «{doc.profstandard.title}» ({doc.profstandard.order})', confirmed=True, checked_at='2026-10-17'))
    sources += literature_for(text)
    known = {s.bibl for s in sources}
    for i, bibl in enumerate(dict.fromkeys(extra), start=1):
        bibl = bibl.strip()
        if not bibl or bibl in known:
            continue
        matched = match_source(bibl)
        if matched:
            if matched['bibl'] not in known:
                sources.append(Source(id=matched['id'], kind=matched['kind'], bibl=matched['bibl'], url=matched.get('url', ''), confirmed=True))
                known.add(matched['bibl'])
            continue
        if len(sources) < 14:
            sources.append(Source(id=f'llm-{i}', kind='book', bibl=f'{bibl} [не подтверждено]', confirmed=False))
    doc.sources = sources


# --------------------------------------------------------------------------- точечная правка
def node_hash(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


def kit_hashes(doc: ProgramDoc) -> dict[str, str]:
    out = {}
    for q in doc.kit.questions:
        out[q.id] = node_hash(q.model_dump())
    for t in doc.kit.tasks:
        out[t.id] = node_hash(t.model_dump())
    for lec in doc.kit.lectures:
        out[lec.id] = node_hash(lec.model_dump())
    for m in doc.modules:
        out[m.id + ':hours'] = node_hash(m.hours.model_dump())
        for t in m.topics:
            out[t.id + ':hours'] = node_hash(t.hours.model_dump())
    for c in doc.competencies:
        out[c.id] = node_hash(c.model_dump())
    return out


def descendants(doc: ProgramDoc, target: str) -> dict[str, list[str]]:
    """Потомки узла по графу связей: что пересоберётся и что останется (FR-36)."""
    topic = next((t for t in doc.all_topics() if t.id == target), None)
    if topic is not None:
        module = next(m for m in doc.modules if topic in m.topics)
        lo = set(topic.lo_ids)
        qs = [q.id for q in doc.kit.questions if q.module_id == module.id and set(q.lo_ids) & lo]
        tasks = [t.id for t in doc.kit.tasks if t.topic_id == topic.id]
        lecs = [lec.id for lec in doc.kit.lectures if lec.topic_id == topic.id]
        return {
            'rebuild': [f'Тема {topic.n} в программе и УТП', *[f'План лекции и слайды {topic.n}' for _ in lecs], f'{len(qs)} вопрос(а) теста модуля {module.n}', *[f'Задание семинара {topic.n} и критерии' for _ in tasks]],
            'nodes': [topic.id, *qs, *tasks, *lecs],
            'keep': ['Учебный план и все часы', 'Компетенции и остальные РО', 'Остальные модули и их материалы', 'Итоговая аттестация'],
        }
    q = next((x for x in doc.kit.questions if x.id == target), None)
    if q is not None:
        return {'rebuild': [f'Вопрос {q.id}'], 'nodes': [q.id], 'keep': ['Часы, темы и РО', 'Остальные вопросы и материалы']}
    t = next((x for x in doc.kit.tasks if x.id == target), None)
    if t is not None:
        return {'rebuild': [f'{t.title} и критерии'], 'nodes': [t.id], 'keep': ['Часы, темы и РО', 'Остальные материалы']}
    if target.startswith('test-'):
        qs = [x.id for x in doc.kit.questions if x.assessment_id == target]
        return {'rebuild': [f'{len(qs)} вопросов теста'], 'nodes': qs, 'keep': ['Часы, темы и РО', 'Задания, лекции и слайды']}
    raise NotFound(f'Элемент {target} не найден в комплекте')


async def edit(doc: ProgramDoc, target: str, instruction: str, new_title: str = '', dry_run: bool = False) -> dict[str, Any]:
    """Точечная правка: пересобираются только потомки узла, затем полная проверка (FR-36…FR-38, V-20)."""
    if doc.status in (Status.ON_APPROVAL, Status.APPROVED):
        raise Conflict('Программа на утверждении: правка недоступна', code='LOCKED')
    if not doc.kit.questions and not doc.kit.tasks:
        raise Conflict('Комплект ещё не собран', code='KIT_NOT_READY')
    plan = descendants(doc, target)
    if dry_run:
        return {'plan': plan, 'applied': False}
    before = kit_hashes(doc)
    allowed = set(plan['nodes'])
    stats = CallStats()
    topic = next((t for t in doc.all_topics() if t.id == target), None)
    if topic is not None:
        module = next(m for m in doc.modules if topic in m.topics)
        old_title = topic.title
        if new_title:
            topic.title = new_title.strip()
        if instruction:
            topic.description = instruction.strip()
        tmp = module.model_copy(deep=True)
        tmp.topics = [t for t in tmp.topics if t.id == topic.id]
        n_q = len([q for q in doc.kit.questions if q.id in allowed])
        res = await content.run(doc, tmp, n_questions=n_q, test_id=next((q.assessment_id for q in doc.kit.questions if q.id in allowed), f'test-{module.id}'),
                                slide_topics={topic.id} if any(lec.topic_id == topic.id and lec.slides for lec in doc.kit.lectures) else set(), stats=stats,
                                instruction_extra=f'Правка методиста: {instruction}. Было: «{old_title}».')
        old_q_ids = [q.id for q in doc.kit.questions if q.id in allowed]
        for qid, nq in zip(old_q_ids, res.questions, strict=False):
            idx = next(i for i, q in enumerate(doc.kit.questions) if q.id == qid)
            nq.id, nq.assessment_id, nq.module_id = qid, doc.kit.questions[idx].assessment_id, module.id
            doc.kit.questions[idx] = nq
        for i, t in enumerate(doc.kit.tasks):
            if t.topic_id == topic.id and res.tasks:
                nt = res.tasks[0]
                nt.id, nt.assessment_id, nt.topic_id, nt.module_id = t.id, t.assessment_id, topic.id, module.id
                doc.kit.tasks[i] = nt
        for i, lec in enumerate(doc.kit.lectures):
            if lec.topic_id == topic.id:
                new_lec = next((x for x in res.lectures), None)
                if new_lec:
                    new_lec.id = lec.id
                    doc.kit.lectures[i] = new_lec
                else:
                    lec.title = topic.title
        for mp in doc.kit.module_programs:
            if mp.module_id == module.id:
                for item in mp.content:
                    if item['topic_id'] == topic.id:
                        item['text'] = res.program.content[0]['text'] if res.program.content else topic.description
    else:
        q = next((x for x in doc.kit.questions if x.id == target), None)
        if q is not None or target.startswith('test-'):
            ids = [target] if q is not None else [x.id for x in doc.kit.questions if x.assessment_id == target]
            for qid in ids:
                question = next(x for x in doc.kit.questions if x.id == qid)
                module = doc.module_by_id(question.module_id or '') or doc.modules[0]
                tmp = module.model_copy(deep=True)
                res = await content.run(doc, tmp, n_questions=1, test_id=question.assessment_id, slide_topics=set(), stats=stats,
                                        instruction_extra=f'Правка методиста к вопросу «{question.stem}»: {instruction}')
                if res.questions:
                    nq = res.questions[0]
                    nq.id, nq.assessment_id, nq.module_id = question.id, question.assessment_id, question.module_id
                    nq.lo_ids = nq.lo_ids or question.lo_ids
                    nq.difficulty = min(5, question.difficulty + (1 if 'слож' in instruction.lower() else 0))
                    doc.kit.questions[doc.kit.questions.index(question)] = nq
        else:
            t = next((x for x in doc.kit.tasks if x.id == target), None)
            if t is not None:
                if instruction:
                    t.criteria.append(Criterion(text=instruction.strip()[:200], points=1)) if 'критери' in instruction.lower() else None
                    if 'критери' not in instruction.lower():
                        t.statement = f'{t.statement} {instruction.strip()}'
    after = kit_hashes(doc)
    changed = {k for k in after if before.get(k) != after[k]}
    leaked = sorted(k for k in changed if k not in allowed and not k.endswith(':hours'))
    hours_changed = sorted(k for k in changed if k.endswith(':hours'))
    ok = not leaked and not hours_changed
    doc.progress['last_edit_check'] = {
        'ok': ok, 'target': target, 'changed': sorted(changed),
        'message': 'Правка изменила элементы вне потомков узла: ' + ', '.join(leaked + hours_changed) if not ok else 'Изменились только потомки узла',
        'nodes': leaked + hours_changed,
    }
    doc.kit.sections = build_sections(doc)
    doc.report = build_report(doc, 'kit')
    for m in doc.modules:
        if m.review_status == 'accepted' and any(n in allowed for n in [x.id for x in m.topics] + [q.id for q in doc.kit.questions if q.module_id == m.id]):
            m.review_status = 'in_review'  # FR-43: изменение принятого модуля возвращает его эксперту
    _stats_to_usage(doc, stats)
    return {'plan': plan, 'applied': True, 'changed': sorted(changed), 'check_ok': ok}


# --------------------------------------------------------------------------- согласование
def blocking_ok(doc: ProgramDoc) -> bool:
    return bool(doc.report and doc.report.stage == 'kit' and doc.report.blocking_passed == doc.report.blocking_total)


def assign_expert(doc: ProgramDoc, module_id: str, expert_id: str) -> None:
    m = doc.module_by_id(module_id)
    if m is None:
        raise NotFound('Модуль не найден')
    m.expert_id = expert_id
    if m.review_status == 'not_started':
        m.review_status = 'in_review'
    if doc.status == Status.KIT_READY:
        if not blocking_ok(doc):
            raise Conflict('Сначала должны пройти все 10 блокирующих проверок', code='BLOCKING_FAILED')
        doc.status = Status.ON_REVIEW


def review_decision(doc: ProgramDoc, module_id: str, actor_id: str, decision: str, comment: str = '') -> None:
    m = doc.module_by_id(module_id)
    if m is None:
        raise NotFound('Модуль не найден')
    if m.expert_id and m.expert_id != actor_id:
        from app.core.errors import ForbiddenRole

        raise ForbiddenRole('Эксперт видит и принимает только назначенные ему модули')
    if decision == 'accept':
        m.review_status = 'accepted'
    elif decision == 'return':
        if not comment.strip():
            raise Conflict('Без комментария вернуть нельзя', code='COMMENT_REQUIRED')
        m.review_status = 'returned'
    elif decision == 'question':
        m.review_status = 'question'
    doc.approvals.append(Approval(stage='module', actor=actor_id, decision='approve' if decision == 'accept' else 'return', comment=comment, module_id=module_id, at=now_iso()))


def add_comment(doc: ProgramDoc, module_id: str, author: str, text: str, node_id: str = '', proposal: str = '') -> Comment:
    c = Comment(id=f'cm{len(doc.comments) + 1}', module_id=module_id, node_id=node_id, author=author, text=text, agent_proposal=proposal, at=now_iso())
    doc.comments.append(c)
    m = doc.module_by_id(module_id)
    if m and m.review_status in ('in_review', 'not_started'):
        m.review_status = 'question'
    return c


def submit(doc: ProgramDoc, actor: str) -> None:
    if not blocking_ok(doc):
        raise Conflict('Отправка доступна после 10 из 10 блокирующих проверок', code='BLOCKING_FAILED')
    not_accepted = [m.n for m in doc.modules if m.review_status != 'accepted']
    if not_accepted:
        raise Conflict(f'Станет доступна, когда все {len(doc.modules)} модулей приняты', code='MODULES_NOT_ACCEPTED', details={'modules': not_accepted})
    doc.status = Status.ON_APPROVAL


def readiness(doc: ProgramDoc) -> dict[str, Any]:
    """Индекс готовности (FR-51): 10 блокирующих проверок + приёмка всех модулей."""
    rep = doc.report
    blocking = rep.blocking_passed if rep and rep.stage == 'kit' else 0
    accepted = sum(1 for m in doc.modules if m.review_status == 'accepted')
    parts_total = 10 + len(doc.modules)
    index = round(100 * (blocking + accepted) / parts_total) if parts_total else 0
    open_items = []
    if rep:
        open_items += [{'title': r.title, 'owner': 'методист'} for r in rep.rules if r.status == 'fail']
    open_items += [{'title': f'Модуль {m.n} не принят', 'owner': m.expert_id or 'методист'} for m in doc.modules if m.review_status != 'accepted']
    return {'index': index, 'blocking': blocking, 'modules_accepted': accepted, 'modules_total': len(doc.modules), 'open': open_items}


def head_decision(doc: ProgramDoc, actor: str, decision: str, comment: str = '') -> None:
    if doc.status != Status.ON_APPROVAL:
        raise Conflict('Программа не на утверждении', code='BAD_STATE')
    if decision == 'approve':
        if readiness(doc)['index'] < 100:
            raise Conflict('Утвердить можно при готовности 100 %', code='NOT_READY', details=readiness(doc))
        doc.status = Status.APPROVED
    else:
        if not comment.strip():
            raise Conflict('Без комментария вернуть нельзя', code='COMMENT_REQUIRED')
        doc.status = Status.RETURNED
    doc.approvals.append(Approval(stage='program', actor=actor, decision='approve' if decision == 'approve' else 'return', comment=comment, at=now_iso()))


__all__ = ['Topic']


def _cap(text: str) -> str:
    """Название программы с прописной буквы, даже если в запросе оно написано строчными."""
    return text[:1].upper() + text[1:] if text else text


class _CodeFix(BaseModel):
    code: str


async def _fix_examples(doc: ProgramDoc, stats: CallStats, report: Callable[[str], Awaitable[None]]) -> None:
    """V-24 до проверки: пример, упавший в песочнице, модель переписывает один раз; не помогло — пример убирается."""
    from app.validation.sandbox import run_detailed

    llm = get_llm()
    checked = 0
    for lec in doc.kit.lectures:
        fixed: list[str] = []
        for code in lec.code_examples:
            checked += 1
            res = await asyncio.to_thread(run_detailed, code) if checked <= 12 else {'ok': True}
            if res['ok']:
                fixed.append(code)
                continue
            new_code = ''
            if llm.enabled:
                try:
                    out = await llm.complete_json(
                        skill='content',
                        system='Исправь учебный пример кода на Python. Только стандартная библиотека, без input(), сети, файлов и сторонних модулей; '
                               'пример запускается сам и печатает результат через print. Уровень — как у аудитории. Верни JSON {"code": "..."}.',
                        user=json.dumps({'audience': doc.params.audience, 'topic': lec.title, 'code': code, 'error': res['error']}, ensure_ascii=False),
                        schema=_CodeFix, temperature=0.2, max_tokens=900, stats=stats,
                    )
                    retry = await asyncio.to_thread(run_detailed, out.code)
                    new_code = out.code if retry['ok'] and out.code.strip() else ''
                except Exception as exc:  # noqa: BLE001 — без модели пример просто убирается
                    logging.getLogger(__name__).warning('пример кода не исправлен: %s', str(exc)[:200])
            if new_code:
                fixed.append(new_code)
                await report(f'песочница · пример к лекции «{lec.title}» исправлен')
            else:
                await report(f'песочница · пример к лекции «{lec.title}» убран: {res["error"][:80]}')
        lec.code_examples = fixed
