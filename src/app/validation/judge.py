"""Судья: 4 смысловых правила (V-21, V-22, V-26, V-27) уточняются моделью рассуждений (FR-33).

Правила кодом дают быструю оценку, судья добавляет замечания по смыслу. Правила не блокирующие:
судья может перевести правило в «предупреждение» и объяснить почему, но не снимает замечаний кода.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.llm.client import CallStats, get_llm
from app.programs.schemas import ProgramDoc, Report

RULES = {
    'V-21': 'Порядок тем учитывает пререквизиты: тема не опирается на то, что изучается позже.',
    'V-22': 'Каждый РО сформулирован проверяемым действием (вычисляет, настраивает), без «понимает», «знаком».',
    'V-26': 'Текст на русском языке, термины поясняются, уровень изложения соответствует аудитории.',
    'V-27': 'Обещания реалистичны для объёма и входного уровня; разрыв с ожиданиями заказчика показан методисту.',
}


class Verdict(BaseModel):
    rule: str
    status: Literal['pass', 'warn'] = 'pass'
    messages: list[str] = Field(default_factory=list)


class JudgeOut(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


def _view(doc: ProgramDoc) -> dict:
    # Только то, что нужно четырём правилам: короткий вход — короткое рассуждение, ответ укладывается в 4096 токенов
    return {
        'title': doc.title,
        'type': doc.template,
        'volume_h': doc.volume_h,
        'audience': doc.params.audience,
        'entry_level': doc.params.entry_level,
        'customer_expectation': doc.params.customer_expectation,
        'goal': doc.goal,
        'outcomes': [f'{lo.code}: {lo.text}' for lo in doc.all_outcomes()],
        'modules': [
            {'n': m.n, 'title': m.title, 'hours': m.hours.total,
             'topics': [f'{t.n} {t.title}' for t in m.topics]}
            for m in doc.modules
        ],
        'sample_text': [mp.annotation[:200] for mp in doc.kit.module_programs[:2]],
        'agent_notes': [n[:160] for n in doc.agent_notes[-3:]],
    }


async def judge(doc: ProgramDoc, stats: CallStats | None = None) -> list[str]:
    """Вызывает судью и сохраняет замечания в комплекте; возвращает журнал."""
    llm = get_llm()
    if not (get_settings().llm_judge_enabled and llm.enabled):
        return []
    system = (
        'Ты — эксперт-методист, проверяешь программу дополнительного образования по четырём правилам. '
        'Для каждого правила верни status pass или warn и 0–3 коротких конкретных замечания с номерами тем или кодами РО. '
        'Замечание — только если нарушение явное. Не рассуждай вслух: ответ — сразу JSON до 300 токенов, без пояснений: {"verdicts": [{"rule": "V-21", "status": "pass", "messages": []}]}.'
    )
    user = json.dumps({'rules': RULES, 'program': _view(doc)}, ensure_ascii=False)
    try:
        out: JudgeOut = await llm.complete_json(
            skill='judge', role='judge', system=system, user=user, schema=JudgeOut, temperature=0.0, max_tokens=4096, stats=stats,
        )
    except Exception as exc:  # noqa: BLE001 — без судьи остаются оценки кода
        logging.getLogger(__name__).warning('судья недоступен: %s', str(exc)[:200])
        return []
    doc.kit.judge = {}
    for v in out.verdicts:
        msgs = [m.strip() for m in v.messages[:3] if m.strip()]
        if v.rule in RULES and v.status == 'warn' and msgs:
            doc.kit.judge[v.rule] = msgs
    return [f'{k}: {v[0]}' for k, v in doc.kit.judge.items()]


def merge(doc: ProgramDoc, report: Report) -> None:
    """Замечания судьи — в отчёт: правило становится предупреждением, замечания кода сохраняются."""
    for rule in report.rules:
        msgs = doc.kit.judge.get(rule.id)
        if msgs:
            rule.status = 'warn' if rule.status == 'pass' else rule.status
            rule.messages += [f'Судья: {m}' for m in msgs]
