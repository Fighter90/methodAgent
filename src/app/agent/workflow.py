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
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.agent.sections import build_sections
from app.core.config import get_settings
from app.core.db import now_iso
from app.core.errors import AppError, BadRequest, Conflict, NotFound
from app.kb.registry import (
    find_ps,
    for_school,
    literature_for,
    match_source,
    registry,
    registry_domains,
)
from app.llm.client import LIMIT_MSG, CallStats, LLMUnavailable, get_llm
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
    StepError,
    Task,
    Topic,
)
from app.skills.clarify import run as clarify
from app.skills.classify import run as classify
from app.skills.content import run as content
from app.skills.intake import run as intake
from app.skills.skeleton import run as skeleton
from app.solver.calendar import (
    CalendarOptionOut,
    CalendarOut,
    apply_option,
    plan_calendar,
)
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
from app.validation.rules import _PREREQ as _V21_PREREQ

logger = logging.getLogger(__name__)

ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop(_: dict[str, Any]) -> None:
    return None


def _stats_to_usage(doc: ProgramDoc, stats: CallStats, step: str = '') -> None:
    """Токены шага — в doc.usage; отказы навыков — в doc.step_errors и в заметки агента."""
    for f in stats.fallbacks:
        doc.step_errors.append(StepError(step=step, skill=f['skill'], module=f.get('module', ''), error=f['error'], fallback=f['fallback'], at=now_iso()))
        where = f' (модуль {f["module"]})' if f.get('module') else ''
        note = f'Навык {f["skill"]}{where}: {f["error"][:120]} — использовано: {f["fallback"]}.'
        if note not in doc.agent_notes:
            doc.agent_notes.append(note)
    stats.fallbacks.clear()
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
    _classify(doc)
    if params.reference_used and not references:
        _note_known_sample(doc)
    doc.questions = clarify.run(doc.params)
    _stats_to_usage(doc, stats, 'intake')
    doc.timing_s['intake'] = round(time.monotonic() - started, 2)


def _note_known_sample(doc: ProgramDoc) -> None:
    """Образец из реестра организации, на который ссылается запрос: известные ошибки часов не переносим."""
    kind = doc.type.value if doc.type else ''
    for s in registry().get('org', {}).get('samples', []):
        if s.get('type') == kind and s.get('issues'):
            doc.agent_notes.append(
                f'В образце АЦР «{s["name"]}» ({s["volume_h"]} ч) итоговые строки учебного плана не сходятся: '
                + '; '.join(s['issues']) + f'. Ошибки не перенесены: {s.get("fix", "часы пересчитаны")}.'
            )
            return


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


def _hours_brief(h: Hours) -> str:
    return f'{h.total} ч (ЛК {h.lk} · ПР {h.pr} · ЛБ {h.lb} · СРС {h.srs})'


def _skeleton_snapshot(doc: ProgramDoc) -> dict[str, Any]:
    """Снимок каркаса перед перестроением — для «что агент изменил по вашему комментарию» (MET-14)."""
    return {
        'modules': {m.id: m.title for m in doc.modules},
        'topics': {t.id: (t.title, t.hours.model_dump()) for t in doc.all_topics()},
        'outcomes': {lo.id: lo.text for lo in doc.all_outcomes()},
    }


def _record_return_changes(doc: ProgramDoc, before: dict[str, Any] | None) -> None:
    """MET-14 (демо 19.10): изменения каркаса по комментарию — узлы «было → стало» в данных программы.

    `progress.return_changes` — краткий список: названия и часы тем, названия модулей,
    формулировки РО, добавленные и удалённые темы. Суммы часов он не меняет. Пустой
    список означает: каркас не менялся (например, модель недоступна).
    """
    if before is None:
        return
    changes: list[dict[str, str]] = []
    for m in doc.modules:
        old = before['modules'].get(m.id)
        if old and old != m.title:
            changes.append({'node': m.id, 'kind': 'module', 'label': f'Модуль {m.n}', 'before': old, 'after': m.title})
    seen: set[str] = set()
    for m in doc.modules:
        for t in m.topics:
            seen.add(t.id)
            old = before['topics'].get(t.id)
            label = f'Тема {t.n}'
            if old is None:
                changes.append({'node': t.id, 'kind': 'added', 'label': label, 'before': '', 'after': t.title})
                continue
            if old[0] != t.title:
                changes.append({'node': t.id, 'kind': 'title', 'label': label, 'before': old[0], 'after': t.title})
            if old[1] != t.hours.model_dump():
                changes.append({'node': t.id, 'kind': 'hours', 'label': f'{label} «{t.title}»',
                                'before': _hours_brief(Hours(**old[1])), 'after': _hours_brief(t.hours)})
    for tid, (title, _h) in before['topics'].items():
        if tid not in seen:
            changes.append({'node': tid, 'kind': 'removed', 'label': 'Тема (удалена)', 'before': title, 'after': ''})
    for lo in doc.all_outcomes():
        old = before['outcomes'].get(lo.id)
        if old and old != lo.text:
            changes.append({'node': lo.id, 'kind': 'outcome', 'label': lo.code, 'before': old[:120], 'after': lo.text[:120]})
    doc.progress['return_changes'] = changes[:40]
    if changes:
        brief = '; '.join(f'{c["label"]}: {c["before"] or "—"} → {c["after"] or "—"}' for c in changes[:3])
        doc.agent_notes.append(f'Изменения по вашему комментарию ({len(changes)}): {brief}.' + (' …' if len(changes) > 3 else ''))


# --------------------------------------------------------------------------- шаг 3
def _final_hours(doc: ProgramDoc) -> int:
    p = doc.params
    if p.final_assessment_hours:
        return p.final_assessment_hours
    v = p.volume_h or 72
    if doc.type == ProgramType.DOOP:
        return 2 if v <= 24 else 4
    return 2 if v <= 36 else 4 if v <= 144 else 6


def _module_by_hint(doc: ProgramDoc, hint: str) -> tuple[Module, str] | None:
    """Модуль для слайдов по подсказке запроса (аудит 19.10, MET-35/F13).

    Ищет по названию модуля и по ВСЕМ его темам (аудит: pandas во второй теме
    модуля 2 не находился, слайды уходили в первый модуль). Возвращает модуль
    и краткое пояснение, по чему он найден.
    """
    low = hint.lower()
    keys = {low[:5], *(w for w in re.findall(r'[a-zа-яё0-9]{4,}', low))}
    for m in doc.modules:
        if any(k in m.title.lower() for k in keys):
            return m, 'по названию модуля'
        hit = next((t for t in m.topics if any(k in t.title.lower() for k in keys)), None)
        if hit is not None:
            return m, f'по теме {hit.n} «{hit.title}»'
    return None


def _resolve_slide_modules(doc: ProgramDoc) -> None:
    mat = doc.params.materials
    if mat.slides_topic_hint and not mat.slides_modules:
        found = _module_by_hint(doc, mat.slides_topic_hint)
        if found:
            m, how = found
            mat.slides_modules = [m.n]
            doc.agent_notes.append(f'Слайды привязаны к модулю {m.n} «{m.title}» ({how}) — по запросу «{mat.slides_topic_hint}».')
    if not mat.slides_modules and not mat.slides_lessons:
        first = next((m for m in doc.modules if m.hours.lk > 0), doc.modules[0] if doc.modules else None)
        if first:
            mat.slides_modules = [first.n]
            doc.assumptions.append(Assumption(field='slides_modules', value=[first.n], source='профиль АЦР: слайды хотя бы для одного модуля'))
    elif not mat.slides_modules and mat.slides_lessons:
        # MET-35: подтверждаем, каким модулям и темам соответствуют запрошенные занятия
        topics = slide_topic_ids(doc)
        mods = sorted({m.n for m in doc.modules for t in m.topics if t.id in topics})
        if mods:
            sess = doc.calendar.session_hours or 2
            doc.agent_notes.append(f'Занятия {mat.slides_lessons} (занятие = {sess} ч) — это {len(topics)} тем модулей {mods}: слайды строятся по ним.')


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


def _schedule_items(doc: ProgramDoc) -> list[tuple]:
    items = [(f'Тема {t.n}. {t.title}', t.hours.total, {k: getattr(t.hours, k) for k in KINDS}) for t in doc.all_topics()]
    items.append((f'Итоговая аттестация: {doc.final_assessment.form}', doc.final_assessment.hours, {'ia': doc.final_assessment.hours}))
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
        options=[CalendarOptionOut(**o.model_dump()) for o in c.options],
    )
    out = apply_option(out, option_id, doc.volume_h, _schedule_items(doc))
    doc.calendar = _to_calendar(out, chosen=option_id)


async def skeleton_step(doc: ProgramDoc, comment: str = '') -> None:
    """Каркас ≤ 180 с: структура от модели, часы — солвер, затем проверка V-01…V-27 (каркасные)."""
    if doc.type is None:
        raise Conflict('Сначала ответьте на вопросы: тип программы не определён', code='QUESTIONS_PENDING')
    stats = CallStats()
    started = time.monotonic()
    before = _skeleton_snapshot(doc) if comment and doc.modules else None  # MET-14: что было до перестроения
    if doc.norm_mode == 'org' and not any(n.startswith(('Использую документы организации', 'Режим «документы организации»')) for n in doc.agent_notes):
        from app.agent.extras import apply_org_docs

        await apply_org_docs(doc)
    if not doc.norm_fragments:
        from app.agent.extras import apply_norms

        apply_norms(doc)
    structure = [s for r in doc.references for s in r.structure]
    current = _skeleton_brief(doc) if comment and doc.modules else None
    draft = await skeleton.run(doc.params, doc.type, doc.profstandard, structure, stats, comment, current, doc.org_fragments, doc.norm_fragments)
    if current and draft.source != 'llm':
        # Модель недоступна: каркас, который методист уже проверял, не заменяем типовым
        doc.agent_notes.append(f'Комментарий «{comment[:200]}» не обработан: модель недоступна, каркас оставлен без изменений — правьте вручную.')
        _limit_note(doc)
        doc.report = build_report(doc, 'skeleton')
        doc.status = Status.SKELETON
        _record_return_changes(doc, before)
        _stats_to_usage(doc, stats, 'skeleton')
        return
    if draft.source != 'llm':
        doc.agent_notes.append('Каркас собран по типовой структуре направления (модель недоступна) — проверьте темы.')
    _limit_note(doc)
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
    _record_return_changes(doc, before)
    _stats_to_usage(doc, stats, 'skeleton')
    doc.timing_s['skeleton'] = round(time.monotonic() - started + doc.timing_s.get('intake', 0), 2)


def _skeleton_brief(doc: ProgramDoc) -> dict[str, Any]:
    return {
        'goal': doc.goal,
        'competencies': [{'code': c.code, 'title': c.title, 'outcomes': [lo.text for i in c.indicators for lo in i.outcomes]} for c in doc.competencies],
        'modules': [{'n': m.n, 'title': m.title, 'hours': m.hours.total, 'topics': [t.title for t in m.topics]} for m in doc.modules],
    }


def _expectation_note(doc: ProgramDoc) -> None:
    exp = doc.params.customer_expectation
    if exp and not any('ожидани' in n.lower() for n in doc.agent_notes):
        doc.agent_notes.append(
            f'Ожидание заказчика: «{exp}». За {doc.volume_h} ч слушатели достигают начального уровня по ключевым '
            f'компетенциям; полная подготовка специалиста требует большего объёма и практики. Разрыв стоит согласовать с заказчиком.'
        )


def recompute(doc: ProgramDoc) -> None:
    """Пересчёт после правки часов методистом: темы перераспределяются солвером внутри модуля.

    Если методист задал часы тем вручную (manual_topics): модуль равен сумме тем, солвер их не трогает (FR-17).
    """
    for m in doc.modules:
        if m.manual_topics:
            for k in KINDS:
                setattr(m.hours, k, sum(getattr(t.hours, k) for t in m.topics))
            for t in m.topics:
                t.hours.total = t.hours.kinds_sum()
            m.hours.total = m.hours.kinds_sum()
            continue
        m.hours.total = m.hours.kinds_sum()
        if m.topics:
            from app.solver.hours import _split_topics

            rows = _split_topics(HoursRow(**m.hours.model_dump()), [TopicIn(t.title, t.weight) for t in m.topics])
            for t, r in zip(m.topics, rows, strict=True):
                t.hours = Hours(**r.as_dict())
    chosen = doc.calendar.chosen_option
    plan_doc_calendar(doc)
    if chosen and doc.calendar.conflict and any(o.id == chosen for o in doc.calendar.options):
        choose_calendar_option(doc, chosen)
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
                m.manual_topics = False  # новые часы модуля — темы снова распределяет солвер
        for tp in mp.get('topics', []):
            t = next((x for x in m.topics if x.id == tp.get('id')), None)
            if t and 'title' in tp:
                t.title = str(tp['title'])[:200]
            if t and tp.get('hours'):
                for k in KINDS:
                    if k in tp['hours']:
                        setattr(t.hours, k, max(0, int(tp['hours'][k])))
                m.manual_topics = True
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
        if rule_id == 'V-21' and '>' in node:
            _swap_topics(doc, *node.split('>', 1))
            if not _apply_dependency_order(doc):  # MET-41: порядок всех тем пересчитывается по единому графу
                doc.agent_notes.append('Граф зависимостей тем содержит цикл: автоматически порядок не восстановить — исправьте темы вручную.')
    doc.decisions.append(Decision(rule_id=rule_id, node=node, proposal=proposal, decision=decision, actor=actor, at=now_iso()))
    doc.report = build_report(doc, 'skeleton')


def _swap_topics(doc: ProgramDoc, a_id: str, b_id: str) -> None:
    """V-21: темы меняются содержанием, позиции и часы остаются — суммы модулей не сдвигаются.

    MET-61 (аудит 22.10): вместе с содержанием перестановку учитывают и ссылки
    prerequisites — они указывают на смысловые темы, поэтому после обмена
    «Классы требуют Циклы» остаётся связкой тех же тем, а не номеров позиций.
    """
    topics = {t.id: t for t in doc.all_topics()}
    a, b = topics.get(a_id), topics.get(b_id)
    if not a or not b:
        return
    for f in ('title', 'description', 'lo_ids', 'prerequisites'):
        va, vb = getattr(a, f), getattr(b, f)
        setattr(a, f, vb)
        setattr(b, f, va)
    flip = {a_id: b_id, b_id: a_id}
    for t in topics.values():  # MET-61: ссылка на переставленную тему следует за её содержанием
        t.prerequisites = [flip.get(p, p) for p in t.prerequisites]


_EXTRA_PREREQ = [(('цикл', 'услов'), ('переменн',))]  # циклы и условия опираются на переменные (MET-41)


def _topic_deps(doc: ProgramDoc) -> tuple[dict[str, set[str]], bool]:
    """Единый граф зависимостей тем (MET-41/F22): ключ — тема, значение — темы, которые должны идти раньше.

    Явные `prerequisites` тем — жёсткие ограничения: их цикл означает, что корректного
    порядка не существует (второе значение — True, утверждать такой каркас нельзя).
    Эвристика опорных тем V-21 и базовые связки — мягкие: дуга, замыкающая цикл,
    не добавляется. Итоговый граф всегда ацикличен.
    """
    topics = doc.all_topics()
    ids = {t.id for t in topics}
    deps: dict[str, set[str]] = {t.id: set() for t in topics}
    for t in topics:
        for p in t.prerequisites:
            if p in ids and p != t.id:
                deps[t.id].add(p)
    hard_cycle = _cycle_in(deps)

    def reaches(src: str, dst: str) -> bool:  # dst уже должен идти раньше src?
        seen: set[str] = set()
        stack = [src]
        while stack:
            x = stack.pop()
            if x == dst:
                return True
            for y in deps.get(x, ()):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return False

    if not hard_cycle:
        low = {t.id: t.title.lower() for t in topics}
        for advanced, basics in (*_V21_PREREQ, *_EXTRA_PREREQ):
            adv = next((t.id for t in topics if any(a in low[t.id] for a in advanced)), '')
            if not adv:
                continue
            for b in basics:
                bas = next((t.id for t in topics if b in low[t.id]), '')
                if bas and adv != bas and not reaches(adv, bas):
                    deps[adv].add(bas)
    return deps, hard_cycle


def _cycle_in(deps: dict[str, set[str]]) -> bool:
    remaining = {k: set(v) for k, v in deps.items()}
    while remaining:
        ready = [k for k, v in remaining.items() if not v]
        if not ready:
            return True
        for k in ready:
            del remaining[k]
        for v in remaining.values():
            v.difference_update(ready)
    return False


def _apply_dependency_order(doc: ProgramDoc) -> bool:
    """MET-41 (F22): раскладывает содержание тем по позициям в топологическом порядке графа зависимостей.

    Позиции, их часы, веса и номера остаются на месте, поэтому итоги модулей и программы
    не меняются. False — в графе жёсткий цикл зависимостей: порядок не тронут, решение
    за методистом (молчаливое утверждение такого каркаса запрещено).
    """
    deps, hard_cycle = _topic_deps(doc)
    if hard_cycle:
        return False
    slots = [t for m in doc.modules for t in m.topics]
    pos = {t.id: i for i, t in enumerate(slots)}
    remaining = {k: set(v) for k, v in deps.items()}
    order: list[str] = []
    while remaining:  # стабильно: при равной готовности берём тему с более ранней текущей позицией
        ready = sorted((k for k, v in remaining.items() if not v), key=pos.__getitem__)
        tid = ready[0]
        order.append(tid)
        del remaining[tid]
        for v in remaining.values():
            v.discard(tid)
    contents = {t.id: {'title': t.title, 'description': t.description, 'lo_ids': t.lo_ids, 'prerequisites': t.prerequisites} for t in slots}
    landing = {tid: slot.id for slot, tid in zip(slots, order, strict=True)}  # MET-61: куда переезжает содержание каждой темы
    titles = []
    changed = False
    for slot, tid in zip(slots, order, strict=True):
        titles.append(contents[tid]['title'])
        if slot.id == tid:
            continue
        for f, v in contents[tid].items():
            setattr(slot, f, list(v) if isinstance(v, list) else v)
        changed = True
    # MET-61: тема переезжает целиком — название, описание, РО и её prerequisites;
    # ссылки prerequisites переписываются на новый адрес той же смысловой темы,
    # иначе правильная до сортировки цепочка «Классы → Циклы → Переменные»
    # превращается в цикл и блокирует утверждение корректной программы
    for t in slots:
        t.prerequisites = [landing.get(p, p) for p in t.prerequisites]
    if changed:
        doc.agent_notes.append('Порядок тем пересобран по зависимостям: ' + ' → '.join(titles[:8]) + ('…' if len(titles) > 8 else ''))
    return True


def approve_skeleton(doc: ProgramDoc, actor: str, *, auto: bool = False) -> None:
    if doc.status not in (Status.SKELETON, Status.RETURNED):
        raise Conflict('Каркас нельзя утвердить в текущем состоянии', code='BAD_STATE')
    report = doc.report or build_report(doc, 'skeleton')
    errors = [r for r in report.rules if r.status == 'fail']
    if auto:
        seen: set[tuple[str, str]] = set()
        for p in report.proposals:
            # Из нескольких вариантов одного пункта берём первый; календарь, выбранный заранее, не трогаем
            key = (p['rule_id'], p.get('node', ''))
            if key in seen or (p['rule_id'] == 'V-10' and doc.calendar.chosen_option):
                continue
            seen.add(key)
            if not p.get('decided'):
                decide(doc, p['rule_id'], 'accept', 'auto-approve', p.get('node', ''), p.get('proposal', ''), p.get('option_id', ''))
        report = doc.report or report
        errors = [r for r in report.rules if r.status == 'fail']
    if _topic_deps(doc)[1]:  # MET-41: цикл зависимостей тем не даёт молчаливого утверждения
        raise Conflict(
            'Порядок тем противоречив: граф зависимостей тем содержит цикл — исправьте темы и их зависимости вручную',
            code='TOPIC_DEPENDENCY_CYCLE',
        )
    if auto:
        left = [p for p in report.proposals if p['rule_id'] == 'V-21' and not p.get('decided')]
        if left:  # MET-41: оставшийся дефект V-21 в auto не проходит молча — нужно явное решение методиста
            raise Conflict('Порядок тем противоречит зависимостям (V-21) — утверждение невозможно без решения методиста',
                           code='DECISIONS_PENDING', details={'pending': left})
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


# MET-48 (аудит 22.10): возврат каркаса возможен, пока программа не собрана и не согласована;
# из поздних состояний он подменял согласованное состояние (старый комплект смешивался с новым каркасом)
_SKELETON_RETURN_ALLOWED = (Status.SKELETON, Status.SKELETON_APPROVED, Status.ON_REVIEW, Status.RETURNED)


def return_skeleton(doc: ProgramDoc, actor: str, comment: str) -> None:
    """Возврат каркаса на доработку с комментарием (FR-24).

    MET-48 (аудит 22.10): IF программа собирается, комплект собран, на утверждении
    или утверждена, THEN возврат каркаса отклоняется (BAD_STATE) — нужна точечная
    правка или новая редакция, а не перестройка каркаса поверх комплекта.
    """
    if doc.status not in _SKELETON_RETURN_ALLOWED:
        raise Conflict('Каркас нельзя вернуть: программа уже собрана или утверждена — используйте точечную правку или новую редакцию',
                       code='BAD_STATE')
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


def _first_module_slide_topics(doc: ProgramDoc) -> set[str]:
    """Слайды нужны хотя бы для одного модуля: запрос их не задал или темы не нашлись — первый модуль с лекциями."""
    m = next((x for x in doc.modules if x.hours.lk > 0), doc.modules[0] if doc.modules else None)
    if m is None:
        return set()
    if m.n not in doc.params.materials.slides_modules:
        doc.params.materials.slides_modules = [*doc.params.materials.slides_modules, m.n]
        doc.assumptions.append(Assumption(field='slides_modules', value=[m.n], source='профиль АЦР: слайды хотя бы для одного модуля'))
    return {t.id for t in m.topics if t.hours.lk > 0} or {t.id for t in m.topics}


def ensure_module_slides(doc: ProgramDoc, kit: Kit, slide_topics: set[str] | None = None) -> None:
    """Гарантия без модели: в комплекте есть слайды хотя бы одного модуля (титул темы и ≥ 3 слайда с тезисами).

    Темы — заказанные в запросе (`slide_topics`), иначе первый модуль с лекционными часами.

    Слайды собираются детерминированно из каркаса (`content._fallback_lecture`): название и описание
    темы, практика, итоги. Модель не нужна, поэтому PPTX не пустой и при LLM_PROVIDERS=fixtures,
    и при отказе шлюза.
    """
    from app.skills.content.run import _fallback_lecture

    if any(lec.slides for lec in kit.lectures):
        return  # слайды уже есть (от модели или шаблона content)
    topics = slide_topics or _first_module_slide_topics(doc)
    if not topics:
        return
    have = {lec.topic_id: lec for lec in kit.lectures}
    for m in doc.modules:
        for t in m.topics:
            if t.id not in topics:
                continue
            built = _fallback_lecture(m, t)
            if t.id in have:
                have[t.id].slides = built.slides
            else:
                kit.lectures.append(built)
    doc.agent_notes.append('Слайды модуля собраны по каркасу без модели (титул, назначение, понятия, практика, итоги) — проверьте тезисы.')


@dataclass
class ModuleRun:
    """Результат задачи одного модуля: содержание и своя статистика вызовов (без общих изменяемых данных)."""

    module: Module
    content: Any
    stats: CallStats


async def generate_kit(doc: ProgramDoc, progress: ProgressFn = _noop) -> None:
    """Комплект: модули параллельно, затем разделы шаблона, источники, проверка и repair."""
    if doc.status not in (Status.SKELETON_APPROVED, Status.KIT_READY, Status.GENERATING):
        raise Conflict('Пока каркас не утверждён, содержание не генерируется', code='SKELETON_NOT_APPROVED')
    doc.status = Status.GENERATING
    started = time.monotonic()
    stats = CallStats()
    slide_topics = slide_topic_ids(doc) or _first_module_slide_topics(doc)
    final_split = _distribute_final_test(doc)
    kit = Kit()
    module_state = {m.id: {'n': m.n, 'title': m.title, 'status': 'ждёт', 'parts': ''} for m in doc.modules}
    feed: list[dict[str, str]] = []

    workers = max(4, get_settings().gen_workers)
    gate = asyncio.Semaphore(workers)
    # Задачи модулей не пишут в doc и в общий CallStats: у каждой свой ModuleRun со своей статистикой.
    # Общее у них только состояние прогресса (module_state, feed) — его меняют и отправляют под замком,
    # чтобы снимки прогресса не перемешивались. Слияние в doc — после gather, по порядку модулей.
    progress_lock = asyncio.Lock()
    per_module: dict[str, CallStats] = {m.id: CallStats() for m in doc.modules}

    async def _report(extra: str = '', module_id: str = '', status: str = '', parts: str = '') -> None:
        async with progress_lock:
            if module_id:
                module_state[module_id]['status'] = status
                if parts:
                    module_state[module_id]['parts'] = parts
            if extra:
                feed.append({'t': time.strftime('%H:%M:%S'), 'text': extra})
            elapsed = time.monotonic() - started
            done = sum(1 for x in module_state.values() if x['status'] == 'готово')
            eta = round(elapsed / done * (len(module_state) - done), 0) if done else None
            live = CallStats()
            live.merge(stats)
            for ms in per_module.values():
                live.merge(ms)
            await progress({
                'modules': [dict(x) for x in module_state.values()], 'feed': feed[-12:], 'workers': workers, 'llm_slots': get_settings().llm_concurrency,
                'usage': {'tokens': live.tokens_in + live.tokens_out, 'cost_rub': round(live.cost_rub, 2), 'by_skill': live.by_skill},
                'elapsed_s': round(elapsed, 1), 'eta_s': eta, 'done': done, 'total': len(module_state),
            })

    async def _one(m: Module) -> ModuleRun:
        async with gate:
            return await _one_inner(m)

    async def _one_inner(m: Module) -> ModuleRun:
        mstats = per_module[m.id]
        await _report(f'content · модуль {m.n} «{m.title}»', m.id, 'идёт')
        test_id = 'test-final' if final_split else f'test-{m.id}'
        n_q = final_split.get(m.id, 0) if final_split else _n_questions(doc, m)
        try:
            res = await content.run(doc, m, n_questions=n_q, test_id=test_id, slide_topics=slide_topics, stats=mstats)
        except Exception as exc:  # noqa: BLE001 — страховка конвейера: сбой одного модуля не роняет комплект, модуль собирается по шаблону
            logger.exception('generate_kit program=%s skill=content module=%s: сбой, шаблонная сборка', doc.id, m.id)
            mstats.fallback('content', exc, 'шаблон из каркаса (страховка конвейера)', module=m.id)
            res = content.fallback(doc, m, content._module_los(doc, m), n_q, test_id, slide_topics)
        parts = f'тест {len(res.questions)} · задания {len(res.tasks)} · лекции {len(res.lectures)}'
        await _report(f'готово · модуль {m.n}: {parts}', m.id, 'готово', parts)
        return ModuleRun(module=m, content=res, stats=mstats)

    runs = await asyncio.gather(*(_one(m) for m in doc.modules))
    # Детерминированное слияние: порядок модулей каркаса, а не порядок завершения задач
    order = {m.id: i for i, m in enumerate(doc.modules)}
    runs = sorted(runs, key=lambda r: order[r.module.id])
    for r in runs:
        stats.merge(r.stats)
    per_module.clear()  # уже в stats: прогресс дальше считает только общий учёт
    results = [(r.module, r.content) for r in runs]
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
    ensure_module_slides(doc, kit, slide_topics)
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
        llm_interview = {m.id: res.interview for m, res in results}
        used_lo: set[str] = set()
        kit.final_assessment['interview_questions'] = {
            m.title: llm_interview.get(m.id) if len(llm_interview.get(m.id) or []) >= 3 else interview_questions(doc, m, used_lo) for m in doc.modules
        }
    doc.kit = kit
    await _fix_examples(doc, stats, _report)
    _sources(doc, extra_sources)
    await check_source_urls(doc)
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
    _limit_note(doc)
    if get_settings().llm_judge_enabled and get_llm().enabled and not get_llm().limit_reached():
        await _report('judge · смысловые правила V-21, V-22, V-26, V-27')
        for line in await judge(doc, stats):
            await _report('judge · ' + line[:120])
        doc.report = build_report(doc, 'kit')
    doc.status = Status.KIT_READY
    _stats_to_usage(doc, stats, 'kit')
    doc.timing_s['kit'] = round(time.monotonic() - started, 2)
    await _report('Комплект собран')


# Итоговое задание строится от предмета программы (аудит 22.10, MET-49/R05): профиль —
# направление, название, аудитория и темы каркаса, а форма аттестации (проект, экзамен,
# портфолио) задаёт только способ проверки. Поэтому экзамен по Docker — про Docker,
# а не про «атаки и отчёт об инциденте» из чужого домена. Порядок перечня важен:
# специальные направления раньше общих, курс анализа данных (в темах есть и SQL) — раньше SQL.
_FORM_CRITERIA: dict[str, list[tuple[str, int]]] = {
    'project': [('Результат соответствует задаче курса', 3), ('Понятное объяснение результата и ответы на вопросы', 3),
                ('Оформление и соблюдение сроков', 2), ('Есть своя идея или доработка', 2)],
    'exam': [('Задание выполнено полностью', 4), ('Средства предмета использованы корректно', 3),
             ('Отчёт о выполнении оформлен по шаблону', 2), ('Ответ на теоретический вопрос', 1)],
    'portfolio': [('Все три работы выполнены', 3), ('Работы соответствуют предмету курса', 3),
                  ('К каждой работе приложено описание и проверка', 3), ('Соблюдены правила безопасности и работы с данными', 1)],
}
_PROJECT_CRITERIA_CHILD = [('Программа запускается и работает без ошибок', 3), ('В программе есть условия, циклы и переменные', 3),
                           ('Ученик понятно объясняет, как устроена программа', 2), ('Есть своя идея или интересная доработка', 2)]

_FINAL_SUBJECTS: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (('react', 'компонент', 'фронтенд', 'frontend'), {
        'about': 'React',
        'make': 'собрать небольшое веб-приложение из компонентов: интерфейс по макету, рабочие состояние и события',
        'make_child': 'страницу-приложение из готовых компонентов: кнопки, формы и список работают',
        'exam': 'собрать страницу из готовых компонентов, подключить обработку событий и объяснить, как передаются данные между компонентами',
        'portfolio': 'страница по макету из готовых компонентов, интерактивный блок с состоянием и событиями, вывод списка данных на страницу',
        'report': ['Постановка задачи и макет интерфейса', 'Ход работы: компоненты, состояние, обработка событий',
                   'Результат: работающее приложение, скриншоты и ссылка на файлы проекта', 'Презентация для защиты на 5–7 минут'],
        'criteria': {
            'project': [('Приложение запускается и работает без ошибок', 3), ('Интерфейс собран из компонентов, состояние и события работают', 3),
                        ('Автор понятно объясняет устройство приложения', 2), ('Есть своя идея или доработка', 2)],
            'exam': [('Страница собрана и работает по заданию', 4), ('Компоненты и состояние использованы корректно', 3),
                     ('Отчёт о выполнении оформлен по шаблону', 2), ('Ответ на теоретический вопрос', 1)],
            'portfolio': [('Все три работы выполнены и работают', 3), ('Компоненты и разметка оформлены аккуратно', 3),
                          ('К каждой работе приложено описание и проверка результата', 3), ('Соблюдены правила работы с данными', 1)],
        },
    }),
    (('3d', 'blender', 'моделирован', 'трёхмерн'), {
        'about': '3D-моделирование',
        'make': 'собственную 3D-сцену по теме курса: модели, материалы, освещение и рендер',
        'make_child': 'например, 3D-сцену с несколькими моделями, материалами и простой анимацией',
        'exam': 'смоделировать объект по образцу, назначить материалы и подготовить рендер сцены',
        'portfolio': 'три работы: модель по образцу, сцена с материалами и освещением, анимированная сцена с рендером',
        'report': ['Идея и эскиз сцены', 'Ход работы: моделирование, материалы, освещение',
                   'Результат: файлы сцены и готовый рендер', 'Презентация для защиты до 5 минут'],
        'criteria': {
            'project': [('Сцена открывается, модели отображаются корректно', 3), ('В сцене есть свои модели, материалы и композиция', 3),
                        ('Автор понятно объясняет, как создана сцена', 2), ('Есть своя идея или интересная деталь', 2)],
        },
    }),
    (('docker', 'контейнер', 'devops', 'kubernetes', 'ci/cd', 'linux'), {
        'about': 'Docker',
        'make': 'упаковать приложение в Docker: работающий образ, docker-compose.yml и проверенная инструкция запуска',
        'make_child': 'работающий контейнер по готовому образцу: образ собирается, сервис запускается',
        'exam': 'собрать образ из Dockerfile и запустить контейнер с приложением на учебном стенде, объяснив использованные команды и настройки',
        'portfolio': 'три артефакта контейнеризации: Dockerfile приложения, docker-compose.yml из двух сервисов, проверенная инструкция запуска',
        'report': ['Постановка задачи: какое приложение упаковывается', 'Ход работы: образ, compose, запуск и проверка',
                   'Результат: работающие образ и контейнер, файлы проекта', 'Презентация для защиты на 5–7 минут'],
        'criteria': {
            'exam': [('Образ собирается, контейнер запускается и работает', 4), ('Dockerfile и команды использованы корректно', 3),
                     ('Отчёт о выполнении оформлен по шаблону', 2), ('Ответ на теоретический вопрос', 1)],
            'project': [('Образ собирается и контейнер работает без ошибок', 3), ('Dockerfile и compose-файл оформлены корректно', 3),
                        ('Автор понятно объясняет устройство сборки', 2), ('Есть своя идея или доработка', 2)],
        },
    }),
    (('pandas', 'анализ данн', 'датасет', 'numpy', 'matplotlib'), {
        'about': 'анализ данных',
        'make': 'постановка задачи на обезличенном наборе данных, подготовка данных, анализ, визуализация, выводы и рекомендации',
        'make_child': 'работу с набором данных: загрузка, таблица и график с выводом',
        'exam': 'загрузить на учебном стенде набор данных, подготовить его и ответить на аналитический вопрос с графиком',
        'portfolio': 'три аналитические работы: очистка набора данных, сводная таблица с группировкой, график с аналитическим выводом',
        'report': ['Постановка задачи и описание исходных данных (данные обезличены, источник указан)',
                   'Ход решения: подготовка данных, применённые методы и инструменты',
                   'Результаты: таблицы, графики, выводы и рекомендации для заказчика',
                   'Презентация для защиты на 5–7 минут и ссылка на файлы проекта'],
        'criteria': {
            'project': [('Требования к данным соблюдены: данные обезличены, источник описан', 2), ('Корректность обработки и анализа данных', 3),
                        ('Качество визуализации и выводов', 3), ('Защита: ответы на вопросы', 2)],
        },
    }),
    (('sql', 'postgres', 'mysql', 'баз данны'), {
        'about': 'SQL',
        'make': 'комплект SQL-запросов к учебной базе: выборки с условиями, соединения таблиц и отчёт с группировкой',
        'make_child': 'комплект запросов к учебной базе: выборки и отчёт с итогами',
        'exam': 'написать SQL-запросы к учебной базе: выборка с условиями, соединение таблиц и итоговый отчёт с агрегатами',
        'portfolio': 'три работы с SQL: выборки с условиями и сортировкой, соединения таблиц, отчёт с GROUP BY и выводами по данным',
        'report': ['Описание учебной базы и задачи', 'Ход работы: запросы и что они возвращают',
                   'Результат: файл с запросами и результатами выборок', 'Презентация для защиты на 5–7 минут'],
        'criteria': {
            'portfolio': [('Запросы выполняются и возвращают корректные данные', 3), ('Соединения и агрегаты использованы по назначению', 3),
                          ('К каждой работе приложено описание запросов', 3), ('Соблюдены правила работы с учебной базой', 1)],
            'exam': [('Запросы выполняются и возвращают корректные данные', 4), ('Соединения и агрегаты использованы по назначению', 3),
                     ('Отчёт о выполнении оформлен по шаблону', 2), ('Ответ на теоретический вопрос', 1)],
        },
    }),
    (('кибербез', 'атак', 'уязвим', 'инцидент', 'siem', 'wireshark', 'безопасн'), {
        'about': 'кибербезопасность',
        'make': 'комплексную работу по защите учебного стенда: настройка средств защиты, проверка и краткий отчёт',
        'make_child': 'работу по правилам цифровой гигиены: разбор примеров и памятка',
        'exam': 'на учебном стенде обнаружить признаки атаки в журналах, закрыть уязвимость',
        'portfolio': 'три работы: настройка защиты стенда, разбор журналов событий, отчёт об учебном инциденте',
        'report': ['Описание стенда и задачи', 'Ход работы: что настроено и как проверялось',
                   'Результаты и выводы по защите стенда', 'Презентация для защиты на 5–7 минут'],
        'criteria': {
            'exam': [('Задание выполнено на стенде полностью', 4), ('Выбраны корректные средства и настройки', 3),
                     ('Отчёт об инциденте оформлен по шаблону', 2), ('Ответ на теоретический вопрос', 1)],
        },
    }),
    (('учител', 'педагог', 'нейросет', 'урок'), {
        'about': 'ИИ-сервисов в работе учителя',
        'make': 'комплект учебных материалов, созданный с помощью ИИ-сервисов, с проверкой результатов',
        'make_child': 'учебную работу, подготовленную с помощью ИИ-сервиса, с проверкой результата',
        'exam': 'подготовить с помощью ИИ-сервиса учебный материал по заданной теме и проверить его на ошибки',
        'portfolio': 'план урока, комплект заданий для учеников и проверочная работа с критериями — все три материала созданы с помощью ИИ-сервисов',
        'report': ['Три материала, созданных с помощью ИИ, с указанием сервиса и промпта',
                   'Проверка каждого материала на ошибки и соответствие ФГОС',
                   'Краткая рефлексия: что сократило время подготовки и какие риски учтены'],
        'criteria': {
            'portfolio': [('План урока: цели, этапы, соответствие ФГОС', 3), ('Задания: разные уровни сложности, проверены на ошибки', 3),
                          ('Проверочная работа: ключи и критерии оценивания', 3), ('Соблюдены правила безопасности и защиты персональных данных', 1)],
        },
    }),
    (('python', 'питон', 'программирован', 'алгоритм'), {
        'about': 'программированию на Python',
        'make': 'небольшую программу по теме курса: свой замысел, работающий код и объяснение устройства',
        'make_child': 'например, простую игру или чат-бота',
        'exam': 'написать и запустить программу на Python по условию, объяснить использованные конструкции',
        'portfolio': 'три работы на Python: программа по условию, программа с функциями и списками, доработанная своя идея',
        'report': ['Работающая программа или прототип', 'Короткий рассказ: идея, как устроена программа, что получилось',
                   'Демонстрация на защите до 5 минут'],
        'criteria': {
            'project': _PROJECT_CRITERIA_CHILD,
        },
    }),
)


def _final_subject(doc: ProgramDoc) -> dict[str, Any]:
    """Предмет программы для итогового задания (аудит 22.10, MET-49/R05).

    Ищем предмет в направлении, названии, аудитории, модулях, темах и РО каркаса;
    форма аттестации предмет не выбирает. Профиль по умолчанию строится из направления.
    """
    blob = ' '.join([
        doc.title, doc.params.direction, doc.params.audience,
        *(m.title for m in doc.modules), *(t.title for t in doc.all_topics()), *(lo.text for lo in doc.all_outcomes()),
    ]).lower()
    for keys, profile in _FINAL_SUBJECTS:
        if any(k in blob for k in keys):
            return profile
    direction = (doc.params.direction or doc.title or '').strip()
    about = f'«{direction}»' if direction else 'программы'
    return {
        'about': about,
        'make': f'задачу по направлению {about}: постановка задачи, решение, демонстрация и объяснение',
        'make_child': f'работу по теме курса {about}',
        'exam': f'выполнить комплексное практическое задание по материалам программы ({about})',
        'portfolio': f'три работы по темам курса {about} с кратким описанием каждой',
        'report': ['Постановка задачи и описание решения', 'Ход работы: что сделано и какими средствами',
                   'Результат: демонстрация и ссылка на файлы проекта', 'Презентация для защиты на 5–7 минут'],
        'criteria': {},
    }


def _final_assessment(doc: ProgramDoc) -> tuple[dict[str, Any], Task, list[str]]:
    """Итоговое задание и рубрика от предмета программы (аудит 22.10, MET-49/R05).

    Форма аттестации задаёт способ проверки, предмет — о чём задание: направление,
    название и темы каркаса. Заготовки «анализ данных», «планы уроков», «атаки»
    применяются только когда предмет курса действительно им соответствует.
    """
    form = doc.final_assessment.form or 'Зачёт'
    low = form.lower()
    s = _final_subject(doc)
    all_lo = [lo.id for lo in doc.all_outcomes()]
    child = doc.type == ProgramType.DOOP
    report_req: list[str] = []
    if 'отч' in low:
        statement = 'Подготовить и защитить отчёт о стажировке: задачи, выполненные работы, артефакты, выводы.'
        report_req = [
            'Титульный лист и сведения о месте стажировки (без персональных данных наставника)',
            'Цели и задачи стажировки, перечень выполненных работ по каждому разделу программы',
            'Артефакты: рабочие материалы по темам программы — код, конфигурации, документы; ссылки на репозитории',
            'Анализ результатов и выводы, отзыв руководителя стажировки',
            'Объём 10–20 страниц, приложения — по необходимости',
        ]
        criteria = [('Полнота отчёта по всем разделам программы', 3), ('Качество артефактов и их работоспособность', 3),
                    ('Ответы на вопросы комиссии', 2), ('Оформление и соблюдение сроков', 2)]
    elif 'портфолио' in low:
        statement = (f'Собрать портфолио из трёх работ по предмету программы ({s["about"]}): {s["portfolio"]}. '
                     'К каждой работе — краткое описание решения и проверка результата.')
        criteria = s['criteria'].get('portfolio', _FORM_CRITERIA['portfolio'])
        report_req = list(s['report'])
    elif 'экзамен' in low:
        statement = f'Экзамен с практическим заданием: {s["exam"]}; по результату — краткий отчёт о выполнении и ответы на вопросы комиссии.'
        criteria = s['criteria'].get('exam', _FORM_CRITERIA['exam'])
    elif 'проект' in low:
        statement = (
            f'Защитить небольшой собственный проект — {s["make_child"]}: показать, как работает программа, и рассказать, как она устроена.'
            if child else f'Выполнить и защитить проект по предмету программы ({s["about"]}): {s["make"]}. Показать результат и ответить на вопросы.'
        )
        criteria = s['criteria'].get('project', _PROJECT_CRITERIA_CHILD if child else _FORM_CRITERIA['project'])
        report_req = list(s['report'])
    else:
        statement = f'Итоговая аттестация в форме: {form}. Комплексное задание по материалам программы ({s["about"]}).'
        criteria = [('Задание выполнено полностью', 5), ('Ответы на вопросы', 5)]
    task = Task(id='final-task', assessment_id='final', title=f'Итоговая аттестация: {form}', statement=statement,
                expected_result='Результат, соответствующий критериям',
                criteria=[Criterion(text=t, points=p) for t, p in criteria], lo_ids=all_lo)
    doc.final_assessment.description = statement
    return {'form': form, 'hours': doc.final_assessment.hours, 'statement': statement, 'criteria': [c.model_dump() for c in task.criteria]}, task, report_req


def _sources(doc: ProgramDoc, extra: list[str]) -> None:
    text = ' '.join([doc.title, doc.params.direction, ' '.join(m.title for m in doc.modules)])
    sources = list(doc.norm_base)
    if doc.profstandard:
        sources.append(Source(id=f'ps-{doc.profstandard.code}', kind='ps', bibl=f'Профессиональный стандарт {doc.profstandard.code} «{doc.profstandard.title}» ({doc.profstandard.order})', confirmed=True,
                              checked_at=(find_ps(doc.profstandard.code) or {}).get('checked_at', '')))
    school = doc.type == ProgramType.DOOP
    sources += literature_for(text, school=school)
    known = {s.bibl for s in sources}
    for i, bibl in enumerate(dict.fromkeys(extra), start=1):
        bibl = bibl.strip()
        if not bibl or bibl in known:
            continue
        matched = match_source(bibl)
        if matched and school and not for_school(matched):
            continue  # взрослая книга из реестра в программе для школьников не нужна
        if matched:
            if matched['bibl'] not in known:
                sources.append(Source(id=matched['id'], kind=matched['kind'], bibl=matched['bibl'], url=matched.get('url', ''), confirmed=True))
                known.add(matched['bibl'])
            continue
        if len(sources) < 14:
            sources.append(Source(id=f'llm-{i}', kind='book', bibl=f'{bibl} [не подтверждено]', confirmed=False))
    doc.sources = sources


async def check_source_urls(doc: ProgramDoc) -> None:
    """Проверка ссылок источников, которых нет в реестре (F14, аудит 19.10).

    Доступность страницы — это не подтверждённость источника: подтверждение ставится,
    только если домен ссылки есть в реестре (`registry_domains()`). Локальные и служебные
    адреса не опрашиваются и не подтверждаются. В режиме fixtures сетевых проверок нет.
    """

    if get_settings().llm_providers == 'fixtures':
        return  # режим без сети
    todo = [(s, m.group(0).rstrip('.,;)')) for s in doc.sources if not s.confirmed and (m := re.search(r'https?://\S+', s.bibl)) and not _is_local_url(m.group(0))]
    if not todo:
        return
    import httpx

    async def _ok(url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as c:
                r = await c.head(url)
                if r.status_code in (403, 405):
                    r = await c.get(url)
                return r.status_code < 400
        except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError):  # нет сети или сайта: источник остаётся неподтверждённым
            return False

    results = await asyncio.gather(*(_ok(u) for _, u in todo[:8]))
    _apply_source_checks(doc, {u: ok for (_, u), ok in zip(todo, results, strict=False)}, registry_domains())


# --------------------------------------------------------------------------- источники (F14)
_LOCAL_HOST = re.compile(r'^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|::1|\[::1\])')


def _is_local_url(url: str) -> bool:
    """Локальные и служебные адреса не опрашиваются: ни подтверждения, ни SSRF-щупа."""

    m = re.match(r'https?://([^/\s:@]+)', url or '')
    if not m:
        return True
    host = m.group(1).lower().strip('[]').removeprefix('www.')
    return bool(_LOCAL_HOST.match(host)) or host.endswith(('.local', '.internal'))


def _apply_source_checks(doc: ProgramDoc, results: dict[str, bool], trusted: set[str]) -> int:
    """F14: доступность страницы ≠ подтверждённость источника.

    Подтверждение ставится, только если домен ссылки входит в доверенные домены реестра;
    иначе фиксируется лишь проверенная ссылка, а пометка «не подтверждено» сохраняется (V-16).
    Возвращает число реально подтверждённых источников.
    """

    n = 0
    for s in doc.sources:
        if s.confirmed:
            continue
        m = re.search(r'https?://\S+', s.bibl)
        if not m:
            continue
        url = m.group(0).rstrip('.,;)')
        if _is_local_url(url):
            continue
        ok = results.get(url)
        if ok is None:
            continue
        host = re.match(r'https?://([^/\s]+)', url).group(1).lower().removeprefix('www.')
        s.url, s.checked_at = url, now_iso()[:10]
        if ok and any(host == d or host.endswith('.' + d) for d in trusted):
            s.confirmed, s.kind = True, 'url'
            s.bibl = s.bibl.replace(' [не подтверждено]', '') + f' (ссылка проверена {s.checked_at})'
            n += 1
    return n


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
    lec = _lecture_of(doc, target)
    if lec is not None:
        what = f'Слайды и план лекции «{lec.title}»' if lec.slides else f'План лекции «{lec.title}»'
        return {'rebuild': [what], 'nodes': [lec.id], 'keep': ['Часы, темы и РО', 'Тесты и задания', 'Остальные лекции']}
    if target.startswith('hours:'):
        topic = next((t for t in doc.all_topics() if t.id == target[6:]), None)
        if topic is None:
            raise NotFound('Тема не найдена')
        module = next(m for m in doc.modules if topic in m.topics)
        peer = _hours_peer(module, topic)
        nodes = [topic.id + ':hours', *([peer.id + ':hours'] if peer else []),
                 *[lec.id for lec in doc.kit.lectures if lec.topic_id in {topic.id, peer.id if peer else ''}]]
        return {
            'rebuild': [f'Часы темы {topic.n}', *([f'Часы темы {peer.n} (компенсация, итог модуля {module.hours.total} ч не меняется)'] if peer else []),
                        'Хронометраж лекций этих тем'],
            'nodes': nodes,
            'keep': [f'Итог модуля {module.n} и всей программы', 'Компетенции и РО', 'Тесты и задания', 'Остальные модули'],
        }
    raise NotFound(f'Элемент {target} не найден в комплекте')


def _lecture_of(doc: ProgramDoc, target: str):
    """Лекция по её id или по id одного из её слайдов."""
    return next((lec for lec in doc.kit.lectures if lec.id == target or any(sl.id == target for sl in lec.slides)), None)


def _hours_peer(module: Module, topic: Topic) -> Topic | None:
    """Тема, за счёт которой сохраняется итог модуля при правке часов: самая большая из остальных."""
    others = [t for t in module.topics if t.id != topic.id]
    return max(others, key=lambda t: t.hours.total) if others else None


def resolve_target(doc: ProgramDoc, target: str, instruction: str) -> str:
    """FR-36: правка, описанная только текстом, — агент сам находит элемент по словам запроса."""
    if target and target != 'auto':
        return target

    words = {w for w in re.findall(r'\w{4,}', instruction.lower())}
    if not words:
        raise Conflict('Опишите, что изменить, или выберите элемент', code='EDIT_TARGET_REQUIRED')

    def score(text: str) -> int:
        low = text.lower()
        return sum(1 for w in words if w[:6] in low)

    candidates = [(score(t.title), t.id) for t in doc.all_topics()]
    candidates += [(score(q.stem), q.id) for q in doc.kit.questions]
    candidates += [(score(t.title + ' ' + t.statement), t.id) for t in doc.kit.tasks]
    candidates += [(score(lec.title + ' ' + ' '.join(sl.title for sl in lec.slides)), lec.id) for lec in doc.kit.lectures if 'слайд' in instruction.lower() or 'лекци' in instruction.lower()]
    best = max(candidates, default=(0, ''))
    if best[0] == 0:
        raise Conflict('Не нашёл элемент по описанию — выберите тему, вопрос, задание или лекцию', code='EDIT_TARGET_REQUIRED')
    return best[1]


def _edit_guard(doc: ProgramDoc) -> list[str]:
    """Таблица 11: после правки суммы часов сходятся и у каждого РО остаётся не меньше двух средств проверки."""
    from app.validation.rules import v13

    problems = []
    for m in doc.modules:
        if sum(t.hours.total for t in m.topics) != m.hours.total or m.hours.kinds_sum() != m.hours.total:
            problems.append(f'часы модуля {m.n} не сходятся')
        for t in m.topics:
            if t.hours.kinds_sum() != t.hours.total:
                problems.append(f'часы темы {t.n} не сходятся')
    if sum(m.hours.total for m in doc.modules) + doc.final_assessment.hours != doc.volume_h:
        problems.append(f'сумма часов не равна {doc.volume_h}')
    status, msgs, _ = v13(doc, 'kit')
    if status == 'fail':
        problems += msgs[:3]
    return problems


async def edit(
    doc: ProgramDoc, target: str, instruction: str, new_title: str = '', dry_run: bool = False, hours: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Точечная правка: пересобираются только потомки узла, затем полная проверка (FR-36…FR-38, V-20).

    Если правка задела что-то вне потомков, разошлись часы или у РО осталось меньше двух средств проверки,
    она отменяется целиком (таблица 11, V-20), а методист получает пояснение.
    """
    if doc.status in (Status.ON_APPROVAL, Status.APPROVED):
        raise Conflict('Программа на утверждении: правка недоступна', code='LOCKED')
    if not doc.kit.questions and not doc.kit.tasks:
        raise Conflict('Комплект ещё не собран', code='KIT_NOT_READY')
    target = resolve_target(doc, target, instruction)
    plan = descendants(doc, target)
    preview = _preview(doc, target, new_title, hours)
    if dry_run:
        return {'plan': plan, 'applied': False, 'target': target, 'preview': preview}
    snapshot = doc.model_copy(deep=True)
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
            nq.lo_ids = doc.kit.questions[idx].lo_ids  # правка формулировки не переносит проверку на другие РО (V-13)
            doc.kit.questions[idx] = nq
        for i, t in enumerate(doc.kit.tasks):
            if t.topic_id == topic.id and res.tasks:
                nt = res.tasks[0]
                nt.id, nt.assessment_id, nt.topic_id, nt.module_id = t.id, t.assessment_id, topic.id, module.id
                nt.lo_ids = t.lo_ids
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
                    # модель может привязать новый вопрос к другому РО — тогда у прежнего РО остаётся одно средство
                    # и правка отклоняется по V-13; формулировка меняется, связь с РО — нет
                    nq.lo_ids = question.lo_ids or nq.lo_ids
                    nq.difficulty = min(5, question.difficulty + (1 if 'слож' in instruction.lower() else 0))
                    doc.kit.questions[doc.kit.questions.index(question)] = nq
        elif target.startswith('hours:'):
            _apply_hours(doc, target[6:], hours or {})
        elif (lec := _lecture_of(doc, target)) is not None:
            module = doc.module_by_id(lec.module_id) or doc.modules[0]
            tmp = module.model_copy(deep=True)
            tmp.topics = [t for t in tmp.topics if t.id == lec.topic_id]
            res = await content.run(doc, tmp, n_questions=0, test_id=f'test-{module.id}', slide_topics={lec.topic_id} if lec.slides else set(),
                                    stats=stats, instruction_extra=f'Правка методиста к лекции «{lec.title}»: {instruction}')
            new_lec = next((x for x in res.lectures if x.topic_id == lec.topic_id), None)
            if new_lec is not None:
                new_lec.id, new_lec.module_id, new_lec.duration_min = lec.id, lec.module_id, lec.duration_min
                new_lec.slides = new_lec.slides or lec.slides
                doc.kit.lectures[doc.kit.lectures.index(lec)] = new_lec
            if new_title:
                doc.kit.lectures[next(i for i, x in enumerate(doc.kit.lectures) if x.id == lec.id)].title = new_title.strip()
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
    hours_changed = sorted(k for k in changed if k.endswith(':hours') and k not in allowed)
    problems = _edit_guard(doc)
    if leaked or hours_changed or problems:
        # V-20 и таблица 11: правка отменяется целиком, комплект остаётся прежним
        reason = []
        if leaked or hours_changed:
            reason.append('правка задела элементы вне потомков узла: ' + ', '.join((leaked + hours_changed)[:6]))
        reason += problems
        for name in type(doc).model_fields:
            setattr(doc, name, getattr(snapshot, name))
        doc.progress['last_edit_check'] = {'ok': True, 'target': target, 'changed': [], 'rejected': True,
                                           'message': 'Правка отменена: ' + '; '.join(reason), 'nodes': []}
        raise Conflict('Правка отменена: ' + '; '.join(reason), code='EDIT_REJECTED', details={
            'proposal': 'Сохраните связи: уточните формулировку, не меняя РО, или перенесите часы внутри одного модуля',
            'nodes': leaked + hours_changed,
        })
    doc.progress['last_edit_check'] = {'ok': True, 'target': target, 'changed': sorted(changed), 'message': 'Изменились только потомки узла', 'nodes': []}
    doc.kit.sections = build_sections(doc)
    doc.report = build_report(doc, 'kit')
    for m in doc.modules:
        touched = set(module_items(doc, m.id)) | {x.id for x in m.topics}
        if changed & touched or allowed & touched:
            m.accepted_items = [x for x in m.accepted_items if x not in changed and x not in allowed]
            if m.review_status == 'accepted':
                m.review_status = 'in_review'  # FR-43: изменение принятого модуля возвращает его эксперту
    _stats_to_usage(doc, stats, 'edit')
    return {'plan': plan, 'applied': True, 'target': target, 'preview': preview, 'changed': sorted(changed), 'check_ok': True}


def _preview(doc: ProgramDoc, target: str, new_title: str, hours: dict[str, int] | None) -> dict[str, str]:
    """«Было / Станет» для экрана правки: название, часы, формулировка вопроса или задания."""
    topic = next((t for t in doc.all_topics() if t.id == target), None)
    if topic is not None:
        return {'before': topic.title, 'after': new_title.strip() or topic.title}
    if target.startswith('hours:'):
        t = next((x for x in doc.all_topics() if x.id == target[6:]), None)
        if t is not None:
            fmt = lambda h: f'ЛК {h.get("lk", 0)} · ПР {h.get("pr", 0)} · ЛБ {h.get("lb", 0)} · СРС {h.get("srs", 0)}'  # noqa: E731
            cur = t.hours.model_dump()
            return {'before': f'Тема {t.n}: {fmt(cur)}', 'after': f'Тема {t.n}: {fmt({**cur, **(hours or {})})}'}
    q = next((x for x in doc.kit.questions if x.id == target), None)
    if q is not None:
        return {'before': q.stem, 'after': 'Вопрос будет переформулирован по указанию, ключ и РО сохранятся'}
    task = next((x for x in doc.kit.tasks if x.id == target), None)
    if task is not None:
        return {'before': task.statement[:300], 'after': 'Условие и критерии будут уточнены по указанию, РО сохранятся'}
    lec = _lecture_of(doc, target)
    if lec is not None:
        return {'before': lec.title, 'after': new_title.strip() or lec.title}
    return {'before': '', 'after': ''}


def _apply_hours(doc: ProgramDoc, topic_id: str, hours: dict[str, int]) -> None:
    """Правка часов темы после сборки: итог модуля сохраняется за счёт самой большой соседней темы."""
    topic = next((t for t in doc.all_topics() if t.id == topic_id), None)
    if topic is None:
        raise NotFound('Тема не найдена')
    module = next(m for m in doc.modules if topic in m.topics)
    peer = _hours_peer(module, topic)
    for kind in KINDS:
        if kind not in hours:
            continue
        new = int(hours[kind])
        delta = new - getattr(topic.hours, kind)
        if delta and (peer is None or getattr(peer.hours, kind) - delta < 0):
            raise Conflict(f'Не хватает часов {kind.upper()} у соседних тем модуля {module.n}, чтобы сохранить итог модуля', code='HOURS_MISMATCH')
        if new < 0:
            raise Conflict('Часы не могут быть отрицательными', code='HOURS_MISMATCH')
        setattr(topic.hours, kind, new)
        if delta and peer is not None:
            setattr(peer.hours, kind, getattr(peer.hours, kind) - delta)
    for t in (topic, peer):
        if t is None:
            continue
        t.hours.total = t.hours.kinds_sum()
        for lec in doc.kit.lectures:
            if lec.topic_id == t.id:
                lec.duration_min = t.hours.lk * 45
    plan_doc_calendar(doc)


# --------------------------------------------------------------------------- согласование
def blocking_ok(doc: ProgramDoc) -> bool:
    return bool(doc.report and doc.report.stage == 'kit' and doc.report.blocking_passed == doc.report.blocking_total)


def assign_expert(doc: ProgramDoc, module_id: str, expert_id: str) -> None:
    m = doc.module_by_id(module_id)
    if m is None:
        raise NotFound('Модуль не найден')
    if doc.status in (Status.ON_APPROVAL, Status.APPROVED):
        raise Conflict('Программа на утверждении: назначения не меняются', code='LOCKED')
    # FR-35: на вычитку — только комплект, прошедший 10 из 10 блокирующих проверок
    if not blocking_ok(doc):
        raise Conflict('Сначала должны пройти все 10 блокирующих проверок', code='BLOCKING_FAILED')
    m.expert_id = expert_id
    if m.review_status == 'not_started':
        m.review_status = 'in_review'
    if doc.status in (Status.KIT_READY, Status.RETURNED):
        doc.status = Status.ON_REVIEW


def module_items(doc: ProgramDoc, module_id: str) -> list[str]:
    """Элементы модуля для вычитки: рабочая программа, лекции, вопросы, задания (ReviewTask.items_total)."""
    k = doc.kit
    return (
        [f'mp-{module_id}'] * any(mp.module_id == module_id for mp in k.module_programs)
        + [lec.id for lec in k.lectures if lec.module_id == module_id]
        + [q.id for q in k.questions if q.module_id == module_id]
        + [t.id for t in k.tasks if t.module_id == module_id]
    )


def review_items(doc: ProgramDoc, module_id: str) -> tuple[int, int]:
    items = module_items(doc, module_id)
    m = doc.module_by_id(module_id)
    done = len(set(items) & set(m.accepted_items)) if m else 0
    return len(items), done


def review_item_of(doc: ProgramDoc, module_id: str, node_id: str) -> str | None:
    """Элемент вычитки по любой ссылке на него (демо-прогон 19.10, MET-5).

    Ссылкой может быть сам элемент (`mp-m1`, `lec1.1`, `q1.2`, `task1.1`), фрагмент
    (`lec1.1#p2` — пункт плана, `task1.1#c3` — критерий), слайд (считается отметкой его
    лекции) или тема (считается отметкой рабочей программы модуля). None — ссылка не на
    элемент этого модуля: чужой или неизвестный идентификатор модулю не приписывается.
    """
    items = set(module_items(doc, module_id))
    nid = (node_id or '').strip()
    if not nid:
        return None
    if nid in items:
        return nid
    base = nid.partition('#')[0]
    if base in items:
        return base
    lec = _lecture_of(doc, base)  # слайд или фрагмент лекции → её лекция
    if lec is not None and lec.module_id == module_id and lec.id in items:
        return lec.id
    module = doc.module_by_id(module_id)
    if module is not None and any(t.id == base for t in module.topics) and f'mp-{module_id}' in items:
        return f'mp-{module_id}'  # тема → рабочая программа модуля
    return None


def review_decision(doc: ProgramDoc, module_id: str, actor_id: str, decision: str, comment: str = '', node_id: str = '', score: int | None = None) -> None:
    """Решение эксперта по модулю или элементу (FR-49, FR-50).

    Любое ожидаемое «не могу принять» — 4xx с русским текстом (NotFound, Conflict, ForbiddenRole);
    данные комплекта в неожиданном формате не превращают приёмку элемента в 500
    (демо-прогон 19.10, MET-5).
    """
    try:
        _review_decision(doc, module_id, actor_id, decision, comment, node_id, score)
    except AppError:
        raise
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        raise BadRequest('Не удалось принять решение по элементу: данные комплекта в неожиданном формате. '
                         'Обновите программу и повторите; если ошибка повторится, сообщите методисту') from exc


def _review_decision(doc: ProgramDoc, module_id: str, actor_id: str, decision: str, comment: str = '', node_id: str = '', score: int | None = None) -> None:
    m = doc.module_by_id(module_id)
    if m is None:
        raise NotFound('Модуль не найден')
    if m.expert_id != actor_id:
        from app.core.errors import ForbiddenRole

        raise ForbiddenRole('Эксперт видит и принимает только назначенные ему модули')
    if not doc.kit.questions and not doc.kit.tasks:
        raise Conflict('Комплект ещё не собран — вычитывать нечего', code='KIT_NOT_READY')
    if decision == 'accept_item':
        item = review_item_of(doc, module_id, node_id)
        if item is None:
            raise NotFound('Элемент не найден в модуле: отметьте рабочую программу, лекцию, вопрос или задание')
        if item not in m.accepted_items:
            m.accepted_items.append(item)
        if m.review_status in ('not_started', 'question'):
            m.review_status = 'in_review'
        return  # модуль целиком принимает эксперт отдельным решением — с оценкой 1–5 (FR-49, FR-50)
    if decision == 'accept':
        total, done = review_items(doc, module_id)
        if done < total:
            # Таблица 11: «Принять модуль» доступна, когда проверены все элементы
            missing = [x for x in module_items(doc, module_id) if x not in m.accepted_items]
            raise Conflict(f'{done} из {total} элементов проверено — примите каждый элемент модуля', code='ITEMS_NOT_CHECKED',
                           details={'done': done, 'total': total, 'missing': missing})
        m.review_status = 'accepted'
    elif decision == 'return':
        if not comment.strip():
            raise Conflict('Без комментария вернуть нельзя', code='COMMENT_REQUIRED')
        m.review_status = 'returned'
    elif decision == 'question':
        m.review_status = 'question'
    doc.approvals.append(Approval(stage='module', actor=actor_id, decision='approve' if decision == 'accept' else 'return', comment=comment,
                                  module_id=module_id, score=score if decision == 'accept' else None, at=now_iso()))


def restore_into(doc: ProgramDoc, cur: ProgramDoc) -> None:
    """Откат возвращает содержание версии, но не решения людей (FR-38).

    Иначе снимок «утверждена» вернул бы утверждение без руководителя.
    Статус и производные данные согласуются с содержанием версии (демо-прогон 19.10, MET-6):
    снимок каркаса не может остаться «готовым комплектом» или «каркас утверждён» —
    иначе программу нельзя ни утвердить заново, ни править; отчёт, разделы и календарь пересчитываются.
    """
    doc.version = cur.version
    doc.comments, doc.approvals = cur.comments, cur.approvals
    has_kit = bool(doc.kit.questions or doc.kit.tasks)
    for m in doc.modules:
        cm = cur.module_by_id(m.id)
        m.expert_id = cm.expert_id if cm else None
        if cm and cm.expert_id and has_kit:
            # содержание поменялось: принятый модуль снова на вычитке (FR-43)
            m.review_status = 'in_review' if cm.review_status == 'accepted' else cm.review_status
        else:
            m.review_status = 'not_started'  # без комплекта вычитывать нечего
        m.accepted_items = []
    if not has_kit:
        doc.status = Status.SKELETON
    elif doc.status in (Status.ON_REVIEW, Status.ON_APPROVAL, Status.APPROVED, Status.RETURNED) or cur.status in (Status.ON_APPROVAL, Status.APPROVED):
        doc.status = (Status.ON_REVIEW if any(m.expert_id for m in doc.modules) else Status.KIT_READY)
    if has_kit:
        doc.kit.sections = build_sections(doc)
        doc.report = build_report(doc, 'kit')
    else:
        recompute(doc)  # часы тем, календарь и отчёт каркаса от содержания версии


def add_comment(doc: ProgramDoc, module_id: str, author: str, text: str, node_id: str = '', proposal: str = '', affected: list[str] | None = None) -> Comment:
    c = Comment(id=f'cm{len(doc.comments) + 1}', module_id=module_id, node_id=node_id, author=author, text=text, agent_proposal=proposal,
                affected=affected or [], at=now_iso())
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


def _name(user_id: str | None) -> str:
    from app.core.security import users

    if not user_id:
        return 'методист'
    u = users().get(user_id)
    return u.name if u else user_id


def readiness(doc: ProgramDoc) -> dict[str, Any]:
    """Индекс готовности (FR-51): 10 блокирующих проверок + приёмка всех модулей; незакрытые пункты с владельцами."""
    rep = doc.report
    blocking = rep.blocking_passed if rep and rep.stage == 'kit' else 0
    accepted = sum(1 for m in doc.modules if m.review_status == 'accepted')
    parts_total = 10 + len(doc.modules)
    index = round(100 * (blocking + accepted) / parts_total) if parts_total else 0
    open_items = []
    if rep:
        open_items += [{'title': f'{r.id} {r.title}', 'owner': r.owner or 'методист'} for r in rep.rules if r.status == 'fail']
    open_items += [
        {'title': f'Модуль {m.n} «{m.title}» не принят ({_REVIEW_RU.get(m.review_status, m.review_status)})',
         'owner': f'эксперт {_name(m.expert_id)}' if m.expert_id else 'методист: назначить эксперта'}
        for m in doc.modules if m.review_status != 'accepted'
    ]
    return {'index': index, 'blocking': blocking, 'modules_accepted': accepted, 'modules_total': len(doc.modules), 'open': open_items,
            'items': {m.id: list(review_items(doc, m.id)) for m in doc.modules}}


_REVIEW_RU = {'not_started': 'не начата', 'in_review': 'в работе', 'question': 'вопрос', 'accepted': 'принят', 'returned': 'возвращён'}


def quality(doc: ProgramDoc, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Качество комплекта и срок для руководителя (FR-50, таблица 10, экран 10)."""
    from datetime import date, datetime

    k = doc.kit
    elements = len(k.questions) + len(k.tasks) + len(k.lectures)
    human = [e for e in events if e['actor'] not in ('agent', 'auto-approve')]
    edited = {e['node_id'] for e in human if e['action'] == 'edit' and e['node_id']}
    edited |= {c.node_id for c in doc.comments if c.status == 'applied' and c.node_id}
    accepted = [m for m in doc.modules if m.review_status == 'accepted']
    touched_modules = {c.module_id for c in doc.comments} | {
        m.id for m in doc.modules if edited & ({t.id for t in m.topics} | set(module_items(doc, m.id)))}
    scores = [a.score for a in doc.approvals if a.stage == 'module' and a.score]
    examples = sum(len(lec.code_examples) for lec in k.lectures)
    v24 = next((r for r in doc.report.rules if r.id == 'V-24'), None) if doc.report else None
    failed_code = len(v24.messages) if v24 and v24.status != 'pass' else 0

    def _d(s: str) -> date | None:
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00')).date()
        except ValueError:
            return None

    start = _d(doc.created_at) or date.today()
    decided = [a.at for a in doc.approvals if a.stage == 'program' and a.decision == 'approve']
    end = _d(decided[-1]) if decided else date.today()
    days = sum(1 for i in range((end - start).days + 1) if (start.toordinal() + i) % 7 not in (6, 0))  # пн–пт
    decisions = sum(1 for e in human if e['action'] in ('decision', 'skeleton_approved', 'skeleton_patch', 'edit', 'assign', 'comment', 'comment_answer',
                                                         'review_accept', 'review_accept_item', 'review_return', 'submitted', 'approved', 'returned'))
    return {
        'human_edit_share': round(100 * len(edited) / elements) if elements else 0,
        'accepted_without_edits': sum(1 for m in accepted if m.id not in touched_modules),
        'modules_accepted': len(accepted),
        'expert_score': round(sum(scores) / len(scores), 1) if scores else None,
        'code_examples': examples,
        'code_ok_share': round(100 * (examples - failed_code) / examples) if examples else None,
        'work_days': max(days, 1),
        'team_minutes_estimate': decisions * 6,  # оценка: 6 минут на одно решение человека по журналу
        'human_decisions': decisions,
        'generation_rub': round(doc.usage.cost_rub, 2),
        'generation_s': round(sum(v for key, v in doc.timing_s.items() if key in ('skeleton', 'kit')), 1),
    }


# Нормы ручной разработки для оценки эффекта (часы методиста). Ориентир — практика АЦР:
# каркас и нормативная база, планы, рабочие программы, лекции со слайдами, тесты, задания, ИА.
EFFECT_NORMS = {
    'skeleton_h': 6.0, 'plan_h_per_ac_hour': 0.05, 'plan_min_h': 2.0, 'module_program_h': 1.5,
    'lecture_h': 3.0, 'question_h': 0.25, 'task_h': 1.0, 'final_assessment_h': 3.0, 'review_share': 0.25,
}


def effect(doc: ProgramDoc) -> dict[str, Any]:
    """Эффект для защиты (ТЗ, раздел 5): сколько часов методиста экономит программа и сколько стоит генерация."""
    n = EFFECT_NORMS
    k = doc.kit
    parts = {
        'skeleton': n['skeleton_h'],
        'plans': max(n['plan_min_h'], n['plan_h_per_ac_hour'] * (doc.volume_h or 0)),
        'module_programs': n['module_program_h'] * len(doc.modules),
        'lectures': n['lecture_h'] * len(k.lectures),
        'questions': n['question_h'] * len(k.questions),
        'tasks': n['task_h'] * len([t for t in k.tasks if t.assessment_id != 'final']),
        'final_assessment': n['final_assessment_h'],
    }
    manual = round(sum(parts.values()), 1)
    review = round(manual * n['review_share'], 1)
    saved = round(manual - review, 1)
    cost = round(doc.usage.cost_rub, 2)
    return {
        'manual_hours': manual,
        'review_hours': review,
        'saved_hours': saved,
        'generation_rub': cost,
        'rub_per_saved_hour': round(cost / saved, 2) if saved > 0 else None,
        'tokens': doc.usage.tokens_in + doc.usage.tokens_out,
        'generation_s': round(sum(v for key, v in doc.timing_s.items() if key in ('skeleton', 'kit')), 1),
        'breakdown_hours': {key: round(v, 1) for key, v in parts.items()},
        'method': 'Оценка по нормам ручной разработки (EFFECT_NORMS): каркас, планы, рабочие программы, лекции, тесты, задания, ИА; '
                  'вычитка черновика методистом — 25 % от ручной трудоёмкости.',
    }


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


def _limit_note(doc: ProgramDoc) -> None:
    """Методист видит, что текст шаблонный из-за суточного лимита шлюза, а не из-за ошибки агента."""
    note = LIMIT_MSG + ': доработайте помеченные модули или пересоберите комплект завтра.'
    if get_llm().limit_reached() and note not in doc.agent_notes:
        doc.agent_notes.append(note)


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
                except (LLMUnavailable, OSError) as exc:  # модель не ответила или песочница не запустилась: пример убирается
                    logger.warning('program=%s skill=content lecture=%s: пример кода не исправлен: %s', doc.id, lec.id, str(exc)[:200])
                    stats.fallback('content', exc, 'пример кода убран из лекции', module=lec.module_id)
            note = (f'Пример кода к лекции «{lec.title}» не запускался ({res["error"][:80]}) и '
                    + ('исправлен моделью' if new_code else 'убран из лекции'))
            doc.agent_notes.append(note)
            if new_code:
                fixed.append(new_code)
            await report('песочница · ' + note)
        lec.code_examples = fixed


_INTERVIEW = (
    'Покажите артефакт по теме «{t}» (конфигурацию, скрипт или схему) и объясните, как он устроен.',
    'Какие инструменты вы использовали в теме «{t}» и почему выбрали именно их?',
    'С какой проблемой вы столкнулись в теме «{t}» и как её диагностировали?',
    'Как вы проверили, что результат работы по теме «{t}» корректен и воспроизводим?',
    'Что бы вы сделали иначе в задаче по теме «{t}», если бы начинали заново?',
    'Опишите по шагам, как вы выполняли рабочее задание по теме «{t}» и сколько времени оно заняло.',
    'Какие требования безопасности и регламенты компании вы учитывали в теме «{t}»?',
    'Как вы документировали работу по теме «{t}» и где хранится результат?',
    'Какую типичную ошибку новичка в теме «{t}» вы видели или допустили сами и как её избежать?',
    'Как результат работы по теме «{t}» используется командой или заказчиком?',
)


def interview_questions(doc: ProgramDoc, m: Module, used: set[str] | None = None) -> list[str]:
    """Вопросы собеседования с руководителем стажировки: по одному на тему, формулировки не повторяются, плюс вопрос по РО модуля."""
    out = [_INTERVIEW[(m.n + i) % len(_INTERVIEW)].format(t=t.title) for i, t in enumerate(m.topics)]
    los = {lo.id: lo for lo in doc.all_outcomes()}
    used = used if used is not None else set()
    lo = next((los[x] for t in m.topics for x in t.lo_ids if x in los and x not in used), None)
    if lo:
        used.add(lo.id)
        out.append(f'Продемонстрируйте на рабочем примере результат обучения «{lo.text}»: что вы сделали и как это проверить.')
    return out
