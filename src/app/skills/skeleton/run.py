"""Навык skeleton: цель, компетенции З/У/Н, модули и темы с весами (FR-14, FR-16).

Модель задаёт только структуру. Код нормализует идентификаторы, гарантирует,
что каждый РО раскрыт хотя бы в одной теме, и передаёт веса солверу.
"""

from __future__ import annotations

import logging

import json
import re

from pydantic import BaseModel, Field

from app.llm.client import CallStats, get_llm
from app.programs.schemas import (
    Competency,
    Indicator,
    LearningOutcome,
    Module,
    Params,
    ProfStandard,
    ProgramType,
    Topic,
)
from app.skills.base import skill
from app.skills.skeleton.library import generic_domain, pick_domain


class OutcomeLLM(BaseModel):
    code: str = ''
    text: str
    verb: str = ''


class IndicatorLLM(BaseModel):
    kind: str = 'can'
    text: str
    outcomes: list[OutcomeLLM] = Field(default_factory=list)


class CompetencyLLM(BaseModel):
    code: str = ''
    title: str
    indicators: list[IndicatorLLM] = Field(default_factory=list)


class TopicLLM(BaseModel):
    title: str
    description: str = ''
    weight: float = 1.0
    lo: list[str] = Field(default_factory=list)


class ModuleLLM(BaseModel):
    title: str
    weight: float = 0.0
    lk_share: float = 0.33
    srs_share: float = 0.2
    control: str = 'Тест'
    topics: list[TopicLLM] = Field(default_factory=list)


class SkeletonLLM(BaseModel):
    title: str = ''
    goal: str = ''
    competencies: list[CompetencyLLM] = Field(min_length=1)
    modules: list[ModuleLLM] = Field(min_length=1)


class SkeletonDraft(BaseModel):
    title: str
    goal: str
    competencies: list[Competency]
    modules: list[Module]
    source: str  # llm | library | generic


def _module_count_hint(volume: int) -> str:
    if volume <= 24:
        return '3–4 модуля по 1–3 темы'
    if volume <= 80:
        return '5–6 модулей по 2–4 темы'
    if volume <= 200:
        return '6–8 модулей по 3–5 тем'
    return '7–10 модулей по 3–6 тем'


async def run(
    params: Params,
    program_type: ProgramType,
    ps: ProfStandard | None,
    reference_structure: list[str],
    stats: CallStats | None = None,
    comment: str = '',
) -> SkeletonDraft:
    llm = get_llm()
    if llm.enabled:
        spec = skill('skeleton')
        payload = {
            'program_type': {'dpp_pk': 'ДПП повышения квалификации', 'dpp_pk_internship': 'ДПП ПК в форме стажировки', 'doop': 'ДООП (общеразвивающая)'}[program_type.value],
            'title': params.title,
            'direction': params.direction,
            'volume_h': params.volume_h,
            'audience': params.audience,
            'entry_level': params.entry_level,
            'form': params.form,
            'final_assessment': params.final_assessment_form,
            'required_topics': params.required_topics,
            'constraints': params.constraints,
            'customer_expectation': params.customer_expectation,
            'structure_hint': _module_count_hint(params.volume_h or 72),
            'internship': program_type == ProgramType.DPP_PK_INTERNSHIP,
            'profstandard': {'code': ps.code, 'title': ps.title, 'tf': [t.model_dump() for t in ps.tf]} if ps else None,
            'reference_structure': reference_structure[:30],
            'methodist_comment': comment,
        }
        try:
            data: SkeletonLLM = await llm.complete_json(
                skill='skeleton',
                system=spec.instruction,
                user=json.dumps(payload, ensure_ascii=False),
                schema=SkeletonLLM,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
                stats=stats,
            )
            draft = _from_llm(data, params, program_type, ps)
            if len(draft.modules) >= 2:
                return draft
        except Exception as exc:  # noqa: BLE001 — сбой модели или разбора ответа: работает резервная генерация
            logging.getLogger(__name__).warning('%s: резервная генерация (%s: %s)', __name__, type(exc).__name__, str(exc)[:200])
    return from_library(params, program_type, ps)


def _code(prefix: str, i: int) -> str:
    return f'{prefix}-{i}'


def _from_llm(data: SkeletonLLM, params: Params, ptype: ProgramType, ps: ProfStandard | None) -> SkeletonDraft:
    comps: list[Competency] = []
    code_map: dict[str, str] = {}
    prefix = 'К' if ptype == ProgramType.DOOP else 'ПК'
    tf_codes = [t.code for t in ps.tf] if ps else []
    for ci, c in enumerate(data.competencies[:8], start=1):
        inds: list[Indicator] = []
        lo_n = 0
        for ii, ind in enumerate(c.indicators[:6], start=1):
            kind = ind.kind if ind.kind in ('know', 'can', 'own') else 'can'
            outs = []
            for o in ind.outcomes[:3] or [OutcomeLLM(text=ind.text)]:
                lo_n += 1
                new_code = f'РО {ci}.{lo_n}'
                if o.code:
                    code_map[_norm_code(o.code)] = f'lo{ci}.{lo_n}'
                outs.append(
                    LearningOutcome(id=f'lo{ci}.{lo_n}', code=new_code, text=o.text.strip(), verb=o.verb or o.text.split()[0].lower())
                )
            inds.append(Indicator(id=f'c{ci}-i{ii}', kind=kind, text=ind.text.strip(), outcomes=outs))
        comps.append(
            Competency(
                id=f'c{ci}',
                code=_code(prefix, ci),
                title=c.title.strip(),
                ps_code=ps.code if ps and ptype != ProgramType.DOOP else None,
                tf_codes=[tf_codes[(ci - 1) % len(tf_codes)]] if tf_codes and ptype != ProgramType.DOOP else [],
                indicators=inds,
            )
        )
    modules: list[Module] = []
    for mi, m in enumerate(data.modules[:12], start=1):
        topics = []
        for ti, t in enumerate(m.topics[:8], start=1):
            lo_ids = [code_map[k] for k in (_norm_code(x) for x in t.lo) if k in code_map]
            topics.append(
                Topic(id=f't{mi}.{ti}', n=f'{mi}.{ti}', title=t.title.strip(), description=t.description.strip(), weight=max(t.weight, 0.1), lo_ids=list(dict.fromkeys(lo_ids)))
            )
        modules.append(
            Module(
                id=f'm{mi}', n=mi, title=m.title.strip(), weight=max(m.weight, 0.01),
                lk_share=min(max(m.lk_share, 0.0), 0.6), srs_share=min(max(m.srs_share, 0.0), 0.6),
                control=m.control or 'Тест', topics=topics or [Topic(id=f't{mi}.1', n=f'{mi}.1', title=m.title)],
            )
        )
    draft = SkeletonDraft(title=data.title or params.title, goal=data.goal, competencies=comps, modules=modules, source='llm')
    link_outcomes(draft)
    return draft


def _norm_code(code: str) -> str:
    return re.sub(r'[^0-9.]', '', code)


def from_library(params: Params, ptype: ProgramType, ps: ProfStandard | None) -> SkeletonDraft:
    text = ' '.join([params.title, params.direction, params.audience, ' '.join(params.required_topics)])
    domain = pick_domain(text)
    project = 'проект' in params.final_assessment_form.lower()
    if domain is None:
        domain = generic_domain(params.title or params.direction, params.required_topics, project)
    prefix = 'К' if ptype == ProgramType.DOOP else 'ПК'
    tf_codes = [t.code for t in ps.tf] if ps else []
    comps: list[Competency] = []
    for ci, (title, inds) in enumerate(domain['competencies'], start=1):
        indicators = []
        for ii, (kind, text_ind, lo_text) in enumerate(inds, start=1):
            indicators.append(
                Indicator(
                    id=f'c{ci}-i{ii}', kind=kind, text=text_ind,
                    outcomes=[LearningOutcome(id=f'lo{ci}.{ii}', code=f'РО {ci}.{ii}', text=lo_text, verb=lo_text.split()[0].lower())],
                )
            )
        comps.append(
            Competency(
                id=f'c{ci}', code=_code(prefix, ci), title=title,
                ps_code=ps.code if ps and ptype != ProgramType.DOOP else None,
                tf_codes=[tf_codes[(ci - 1) % len(tf_codes)]] if tf_codes and ptype != ProgramType.DOOP else [],
                indicators=indicators,
            )
        )
    modules = []
    for mi, (title, w, lk, srs, topics, control) in enumerate(domain['modules'], start=1):
        modules.append(
            Module(
                id=f'm{mi}', n=mi, title=title, weight=w, lk_share=lk, srs_share=srs, control=control,
                topics=[Topic(id=f't{mi}.{ti}', n=f'{mi}.{ti}', title=t, description=d) for ti, (t, d) in enumerate(topics, start=1)],
            )
        )
    title = params.title or (domain.get('goal', '')[:60])
    draft = SkeletonDraft(title=title, goal=domain['goal'], competencies=comps, modules=modules, source=domain['key'])
    link_outcomes(draft)
    return draft


def _words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r'[a-zа-яё]{4,}', text.lower())}


def link_outcomes(draft: SkeletonDraft) -> None:
    """Каждый РО раскрыт хотя бы в одной теме, у каждой темы есть РО (V-12).

    Связь ищется по пересечению слов РО и темы; если пересечения нет —
    РО закрепляется за наименее нагруженной темой.
    """
    topics = [t for m in draft.modules for t in m.topics]
    if not topics:
        return
    outcomes = [lo for c in draft.competencies for i in c.indicators for lo in i.outcomes]
    covered = {lo_id for t in topics for lo_id in t.lo_ids}
    for lo in outcomes:
        if lo.id in covered:
            continue
        lo_words = _words(lo.text)
        scored = sorted(topics, key=lambda t: (-len(lo_words & _words(t.title + ' ' + t.description)), len(t.lo_ids)))
        scored[0].lo_ids.append(lo.id)
        covered.add(lo.id)
    by_load = sorted(outcomes, key=lambda lo: sum(lo.id in t.lo_ids for t in topics))
    for t in topics:
        if not t.lo_ids and by_load:
            t_words = _words(t.title + ' ' + t.description)
            best = max(by_load, key=lambda lo: len(t_words & _words(lo.text)))
            t.lo_ids.append(best.id)
