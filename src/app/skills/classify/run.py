"""Навык classify: тип программы, шаблон АЦР, нормативная база, ПС из реестра (FR-06, FR-07)."""

from __future__ import annotations

from dataclasses import dataclass

from app.kb.registry import norm_base_for, pick_ps
from app.programs.schemas import Params, ProfStandard, ProgramType, Source

TEMPLATES = {
    ProgramType.DPP_PK: ('ДПП ПК', 'Удостоверение о повышении квалификации'),
    ProgramType.DPP_PK_INTERNSHIP: ('ДПП ПК (стажировка)', 'Удостоверение о повышении квалификации'),
    ProgramType.DOOP: ('ДООП', 'Сертификат об освоении программы'),
}


@dataclass
class ClassifyResult:
    program_type: ProgramType | None
    template: str
    issued_document: str
    norm_base: list[Source]
    profstandard: ProfStandard | None
    confidence: float
    message: str


def infer_type(text: str, params: Params) -> tuple[ProgramType | None, float]:
    if params.program_type:
        return params.program_type, 0.95
    low = text.lower()
    if any(k in low for k in ('школьник', ' класс', 'детей', 'подростк')):
        return ProgramType.DOOP, 0.75
    return None, 0.0


def run(text: str, params: Params) -> ClassifyResult:
    ptype, conf = infer_type(text, params)
    if ptype is None:
        return ClassifyResult(None, '', '', [], None, conf, 'Тип программы из запроса не ясен — уточню у методиста.')
    template, doc = TEMPLATES[ptype]
    norm = norm_base_for(ptype)
    ps = None
    if ptype != ProgramType.DOOP:
        ps = pick_ps(' '.join([text, params.direction, params.title, ' '.join(params.required_topics)]), params.ps_hint)
    if ptype == ProgramType.DOOP:
        msg = 'Это дополнительная общеразвивающая программа, беру шаблон ДООП (273-ФЗ, приказ Минпросвещения № 629). Раздел профстандартов не нужен.'
    else:
        msg = f'Это программа повышения квалификации, беру шаблон {template} (273-ФЗ, приказ Минобрнауки № 499).'
        if ps:
            msg += f' Профстандарт из реестра: {ps.code} «{ps.title}», {ps.order}.'
    return ClassifyResult(ptype, template, doc, norm, ps, conf, msg)
