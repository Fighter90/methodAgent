"""Навык skeleton: цель, компетенции З/У/Н, модули и темы с весами (FR-14, FR-16).

Модель задаёт только структуру. Код нормализует идентификаторы, гарантирует,
что каждый РО раскрыт хотя бы в одной теме, и передаёт веса солверу.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from app.llm.client import MODEL_DATA_ERRORS, CallStats, LLMUnavailable, get_llm
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
from app.skills.skeleton.library import (
    MUST_COVER,
    final_assessment,
    form_kind,
    generic_domain,
    kw_hit,
    pick_domain,
)


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
    tf: str = ''  # код трудовой функции из переданного ПС; проверяется по реестру
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
    current: dict | None = None,
    org_documents: list[dict] | None = None,
    norm_documents: list[dict] | None = None,
) -> SkeletonDraft:
    llm = get_llm()
    must = must_cover(params)
    reason = 'LLM не настроен'
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
            'required_topics': list(dict.fromkeys([*params.required_topics, *(t for t, _d, _k in must)])),
            'constraints': params.constraints,
            'customer_expectation': params.customer_expectation,
            'structure_hint': _module_count_hint(params.volume_h or 72),
            'internship': program_type == ProgramType.DPP_PK_INTERNSHIP,
            'profstandard': {'code': ps.code, 'title': ps.title, 'tf': [t.model_dump() for t in ps.tf]} if ps else None,
            'reference_structure': reference_structure[:30],
            'methodist_comment': comment,
            # Возврат с комментарием (FR-24): модель видит текущий каркас и меняет только указанные части
            'current_skeleton': current,
            'org_documents': (org_documents or [])[:4],
            'norm_documents': [{'act': d['name'], 'text': d['text']} for d in (norm_documents or [])[:4]],
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
            drop_assessment_modules(draft)
            ensure_topics(draft, must)
            if len(draft.modules) >= 2:
                return draft
            reason = f'модель вернула {len(draft.modules)} модуль(ей)'
        except LLMUnavailable as exc:
            logging.getLogger(__name__).warning('skeleton: резервная генерация (%s)', str(exc)[:200])
            reason = str(exc)
        except MODEL_DATA_ERRORS as exc:
            logging.getLogger(__name__).exception('skeleton: ответ модели не разобран, резервная генерация')
            reason = f'{type(exc).__name__}: {exc}'
    return from_library(params, program_type, ps, stats=stats, reason=reason)


def _code(prefix: str, i: int) -> str:
    return f'{prefix}-{i}'


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r'[а-яёa-z]{4,}', text.lower())}


def match_tf(text: str, ps: ProfStandard | None, i: int, proposed: str = '') -> list[str]:
    """ТФ компетенции по смыслу (FR-14): код от модели, если он есть в ПС, иначе наибольшее пересечение основ слов."""
    if not ps or not ps.tf:
        return []
    codes = {t.code for t in ps.tf}
    if proposed.strip() in codes:
        return [proposed.strip()]
    words = _stems(text)
    scored = sorted(((len(words & _stems(t.title)), -k, t.code) for k, t in enumerate(ps.tf)), reverse=True)
    if scored[0][0] > 0:
        return [scored[0][2]]
    return [ps.tf[(i - 1) % len(ps.tf)].code]


def _from_llm(data: SkeletonLLM, params: Params, ptype: ProgramType, ps: ProfStandard | None) -> SkeletonDraft:
    comps: list[Competency] = []
    code_map: dict[str, str] = {}
    prefix = 'К' if ptype == ProgramType.DOOP else 'ПК'
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
                tf_codes=match_tf(c.title + ' ' + ' '.join(i.text for i in c.indicators), ps, ci, c.tf) if ptype != ProgramType.DOOP else [],
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


def _short_title(text: str, limit: int = 60) -> str:
    """Название из цели без обрыва посреди слова и без незакрытой кавычки «."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0].rstrip(' ,:;—-')
    if cut.count('«') > cut.count('»'):
        cut = cut[:cut.rfind('«')].rstrip(' ,:;—-')
    return cut


def _request_text(params: Params) -> str:
    return ' '.join([params.title, params.direction, params.audience, ' '.join(params.required_topics)])


def from_library(
    params: Params,
    ptype: ProgramType,
    ps: ProfStandard | None,
    stats: CallStats | None = None,
    reason: str = '',
) -> SkeletonDraft:
    text = _request_text(params)
    domain = pick_domain(text)
    if domain is None:
        # Направление запроса библиотека не покрывает: честный каркас по запросу, а не чужой домен (SPEC-SKILLS-19)
        if stats is not None:
            stats.fallback('skeleton', reason or 'LLM не настроен', 'каркас по универсальному шаблону, направление из библиотеки не найдено')
        domain = generic_domain(params.title or params.direction, params.required_topics, params.final_assessment_form)
    elif stats is not None:
        stats.fallback('skeleton', reason or 'LLM не настроен', f'типовой каркас направления «{domain["title"]}»')
    prefix = 'К' if ptype == ProgramType.DOOP else 'ПК'
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
                tf_codes=match_tf(title + ' ' + ' '.join(str(x) for x in inds), ps, ci) if ptype != ProgramType.DOOP else [],
                indicators=indicators,
            )
        )
    module_rows = list(domain['modules'])
    # Итоговый модуль домена остаётся только при совпадении вида аттестации (SPEC-SKILLS-19):
    # иначе он строится от формы и предмета запроса, а не из шаблона чужого направления
    wanted = form_kind(params.final_assessment_form)
    if wanted and wanted != form_kind(module_rows[-1][5]):
        final = final_assessment(params.final_assessment_form, params.direction or params.title or domain['title'])
        if final:
            w, lk, srs = module_rows[-1][1:4]
            module_rows = [*module_rows[:-1], (final[0], w, lk, srs, final[1], final[2])]
    modules = []
    for mi, (title, w, lk, srs, topics, control) in enumerate(module_rows, start=1):
        modules.append(
            Module(
                id=f'm{mi}', n=mi, title=title, weight=w, lk_share=lk, srs_share=srs, control=control,
                topics=[Topic(id=f't{mi}.{ti}', n=f'{mi}.{ti}', title=t, description=d) for ti, (t, d) in enumerate(topics, start=1)],
            )
        )
    title = params.title or domain.get('title') or _short_title(domain.get('goal', ''))
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


def must_cover(params: Params) -> list[tuple[str, str, tuple[str, ...]]]:
    """Темы направления, релевантные запросу (SPEC-SKILLS-19): темы библиотеки — предложения,
    в каркас попадают только те, что запрос сам называет, и только при распознанном направлении."""
    text = _request_text(params).lower()
    domain = pick_domain(text)
    if domain is None:
        return []
    return [row for row in MUST_COVER.get(domain['key'], []) if any(kw_hit(text, kw) for kw in row[2])]


_ASSESSMENT_MODULE = re.compile(r'итогов\w*\s+аттестац|защит\w*\s+отч|подготовк\w*\s+к\s+(итогов|аттестац|защит)', re.IGNORECASE)


def drop_assessment_modules(draft: SkeletonDraft) -> None:
    """Итоговая аттестация считается отдельной строкой учебного плана: модуль с тем же назначением дублирует её часы."""
    keep = [m for m in draft.modules if not _ASSESSMENT_MODULE.search(m.title)]
    if len(keep) == len(draft.modules) or len(keep) < 2:
        return
    draft.modules = keep
    _renumber(draft)
    link_outcomes(draft)


def ensure_topics(draft: SkeletonDraft, must: list[tuple[str, str, tuple[str, ...]]]) -> None:
    """Обязательные темы направления: если модель пропустила тему, она добавляется в ближайший по смыслу модуль."""
    for title, desc, keys in must:
        text = ' '.join(f'{m.title} {t.title} {t.description}' for m in draft.modules for t in m.topics).lower() + ' '
        if any(k in text for k in keys):
            continue
        t_words = _words(title + ' ' + desc)
        target = max(draft.modules, key=lambda m: (len(t_words & _words(m.title + ' ' + ' '.join(t.title for t in m.topics))), m.weight))
        mi = target.n
        n = len(target.topics) + 1
        target.topics.append(Topic(id=f't{mi}.{n}', n=f'{mi}.{n}', title=title, description=desc, weight=1.0))
    link_outcomes(draft)


def _renumber(draft: SkeletonDraft) -> None:
    for mi, m in enumerate(draft.modules, start=1):
        m.id, m.n = f'm{mi}', mi
        for ti, t in enumerate(m.topics, start=1):
            t.id, t.n = f't{mi}.{ti}', f'{mi}.{ti}'
