"""Навык review_assist: предложение правки по комментарию эксперта в пределах модуля."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from app.llm.client import get_llm
from app.programs.schemas import ProgramDoc
from app.skills.base import skill


class Proposal(BaseModel):
    proposal: str
    new_text: str = ''
    affected: list[str] = Field(default_factory=list)


async def propose(doc: ProgramDoc, module_id: str, node_id: str, comment: str) -> str:
    fragment = ''
    for t in doc.kit.tasks:
        if t.id == node_id:
            fragment = f'{t.title}: {t.statement}; критерии: ' + '; '.join(c.text for c in t.criteria)
    for q in doc.kit.questions:
        if q.id == node_id:
            fragment = q.stem + ' | ' + ' / '.join(q.options)
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
        except Exception as exc:  # noqa: BLE001 — сбой модели или разбора ответа: работает резервная генерация
            logging.getLogger(__name__).warning('%s: резервная генерация (%s: %s)', __name__, type(exc).__name__, str(exc)[:200])
    return f'Учесть замечание эксперта: «{comment}». Правка затронет только этот элемент модуля; часы и РО не меняются.'
