"""Навык review_assist: предложение правки по комментарию эксперта в пределах модуля."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.core.errors import NotFound
from app.llm.client import MODEL_DATA_ERRORS, LLMUnavailable, get_llm
from app.programs.schemas import ProgramDoc
from app.skills.base import skill


class Proposal(BaseModel):
    proposal: str
    new_text: str = ''
    affected: list[str] = Field(default_factory=list)


def fragment_of(doc: ProgramDoc, node_id: str) -> str:
    """Текст фрагмента: задание, критерий (task#c2), вопрос, лекция, пункт плана (lec#p3) или слайд."""
    base, _, part = node_id.partition('#')
    for t in doc.kit.tasks:
        if t.id == base:
            if part.startswith('c') and part[1:].isdigit() and 1 <= int(part[1:]) <= len(t.criteria):
                return f'Критерий задания «{t.title}»: {t.criteria[int(part[1:]) - 1].text}'
            return f'{t.title}: {t.statement}; критерии: ' + '; '.join(c.text for c in t.criteria)
    for q in doc.kit.questions:
        if q.id == base:
            return q.stem + ' | ' + ' / '.join(q.options)
    for lec in doc.kit.lectures:
        if lec.id == base:
            if part.startswith('p') and part[1:].isdigit() and 1 <= int(part[1:]) <= len(lec.plan):
                step = lec.plan[int(part[1:]) - 1]
                return f'Пункт плана лекции «{lec.title}»: {step.get("min", "")} мин — {step.get("text", "")}'
            return f'Лекция «{lec.title}»: ' + '; '.join(str(x.get('text', '')) for x in lec.plan)
        for sl in lec.slides:
            if sl.id == base:
                return f'Слайд «{sl.title}»: ' + '; '.join(sl.bullets)
    return ''


async def propose_full(doc: ProgramDoc, module_id: str, node_id: str, comment: str) -> Proposal:
    """Предложение агента и список затрагиваемых элементов по графу связей (FR-41)."""
    from app.agent.workflow import descendants

    base = node_id.partition('#')[0]
    try:
        affected = descendants(doc, base)['rebuild'] if base else []
    except (NotFound, LookupError):  # комментарий к модулю целиком: элементы не пересобираются
        affected = []
    text = await propose(doc, module_id, node_id, comment)
    return Proposal(proposal=text, affected=affected)


async def propose(doc: ProgramDoc, module_id: str, node_id: str, comment: str) -> str:
    fragment = fragment_of(doc, node_id)
    llm = get_llm()
    if llm.enabled and fragment:
        spec = skill('review_assist')
        try:
            res: Proposal = await llm.complete_json(
                skill='review_assist', system=spec.instruction,
                user=json.dumps({'fragment': fragment, 'comment': comment}, ensure_ascii=False),
                schema=Proposal, temperature=spec.temperature, max_tokens=spec.max_tokens,
            )
            return res.proposal
        except (LLMUnavailable, *MODEL_DATA_ERRORS) as exc:  # модель не ответила или ответ не разобран: шаблонное предложение
            logging.getLogger(__name__).warning('review_assist program=%s module=%s: резервная генерация (%s: %s)',
                                                doc.id, module_id, type(exc).__name__, str(exc)[:200])
    return f'Учесть замечание эксперта: «{comment}». Правка затронет только этот элемент модуля; часы и РО не меняются.'
