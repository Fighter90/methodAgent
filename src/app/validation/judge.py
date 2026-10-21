"""Судья: смысловые правила (V-19, V-21, V-22, V-26, V-27) уточняются моделью рассуждений (FR-33).

Правила кодом дают быструю оценку, судья добавляет замечания по смыслу. Правила не блокирующие:
судья может перевести правило в «предупреждение» и объяснить почему, но не снимает замечаний кода.
Судья видит не только структуру программы, но и сами материалы комплекта: формулировки вопросов
с вариантами и отмеченным ключом, задания с критериями, пункты слайдов и строки планов лекций
(MET-33, находка аудита F11: подмена ключа или английский текст материалов не меняли его вход).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.llm.client import CallStats, LLMUnavailable, get_llm
from app.programs.schemas import Module, ProgramDoc, Report, RuleResult

RULES = {
    'V-19': 'Ключ вопроса указывает на действительно верный вариант, дистракторы не абсурдны.',
    'V-21': 'Порядок тем учитывает пререквизиты: тема не опирается на то, что изучается позже.',
    'V-22': 'Каждый РО сформулирован проверяемым действием (вычисляет, настраивает), без «понимает», «знаком».',
    'V-26': 'Текст, включая вопросы и слайды, на русском языке, термины поясняются, уровень изложения соответствует аудитории.',
    'V-27': 'Обещания реалистичны для объёма и входного уровня; разрыв с ожиданиями заказчика показан методисту.',
}

# Жёсткие лимиты входа судьи (SPEC-JUDGE-07): материалы одного модуля — не больше _MODULE_CHARS
# символов, длинные строки усекаются с «…», элементы сверх лимитов отбрасываются с пометкой «усечено».
_ITEM_CHARS = 200  # формулировка вопроса или задания
_OPTION_CHARS = 60  # вариант ответа
_BULLET_CHARS = 80  # пункт слайда или строка плана
_MAX_QUESTIONS = 12  # вопросов на модуль
_MAX_TASKS = 6  # заданий на модуль
_MAX_SLIDES = 10  # слайдов на модуль
_MAX_PLAN_LINES = 12  # строк планов лекций на модуль
_MODULE_CHARS = 9000  # бюджет символов на материалы одного модуля

_NODE_RX = re.compile(r'^\[([A-Za-z0-9._:\-]+)\]\s*')


class Verdict(BaseModel):
    rule: str
    status: Literal['pass', 'warn'] = 'pass'
    node: str = ''  # узел графа (q1.2, sl1.1.3, task1.1), к которому относится замечание
    messages: list[str] = Field(default_factory=list)


class JudgeOut(BaseModel):
    verdicts: list[Verdict] = Field(default_factory=list)


def _cut(text: str, limit: int) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def _question_line(q) -> str:
    parts = []
    for i, option in enumerate(q.options[:6]):
        mark = '✓' if i == q.key else f'{i + 1})'
        parts.append(f'{mark} {_cut(option, _OPTION_CHARS)}')
    if not 0 <= q.key < len(q.options):
        parts.append(f'ключ {q.key} вне диапазона')
    return f'{q.id}: {_cut(q.stem, _ITEM_CHARS)} — ' + ' | '.join(parts)


def _task_line(t) -> str:
    criteria = '; '.join(f'{_cut(c.text, _BULLET_CHARS)} ({c.points} б.)' for c in t.criteria[:5])
    result = f'; ожидается: {_cut(t.expected_result, 100)}' if t.expected_result.strip() else ''
    return f'{t.id}: {_cut(t.title + ". " + t.statement, _ITEM_CHARS)}{result}; критерии: {criteria or "нет"}'


def _lecture_materials(lec) -> tuple[list[str], list[str]]:
    slides = []
    for sl in lec.slides[:_MAX_SLIDES]:
        bullets = ' · '.join(_cut(b, _BULLET_CHARS) for b in sl.bullets[:4] if str(b).strip())
        slides.append(f'{sl.id} «{_cut(sl.title, _BULLET_CHARS)}»: {bullets or "без пунктов"}')
    plan = [
        f'{p.get("min", "?")} мин — {_cut(str(p.get("text", "")), _BULLET_CHARS)}'
        for p in lec.plan[:_MAX_PLAN_LINES]
        if isinstance(p, dict)
    ]
    return slides, plan


def _module_materials(doc: ProgramDoc, m: Module) -> dict:
    """Реальные материалы модуля для судьи: вопросы с ключами, задания с критериями, слайды, планы (SPEC-JUDGE-07)."""
    left = _MODULE_CHARS
    materials: dict = {}

    def put(key: str, values: list[str], cap: int) -> None:
        nonlocal left
        kept: list[str] = []
        for value in values[:cap]:
            if len(value) > left:
                materials['усечено'] = 'да'
                break
            kept.append(value)
            left -= len(value)
        if kept:
            materials[key] = kept

    questions = [q for q in doc.kit.questions if q.module_id == m.id]
    tasks = [t for t in doc.kit.tasks if t.module_id == m.id]
    slides: list[str] = []
    plans: list[str] = []
    for lec in doc.kit.lectures:
        if lec.module_id != m.id:
            continue
        lec_slides, lec_plan = _lecture_materials(lec)
        slides += lec_slides
        plans += lec_plan
    put('вопросы', [_question_line(q) for q in questions], _MAX_QUESTIONS)
    put('задания', [_task_line(t) for t in tasks], _MAX_TASKS)
    put('слайды', slides, _MAX_SLIDES)
    put('планы', plans, _MAX_PLAN_LINES)
    if len(questions) > _MAX_QUESTIONS or len(tasks) > _MAX_TASKS or len(slides) > _MAX_SLIDES or len(plans) > _MAX_PLAN_LINES:
        materials['усечено'] = 'да'
    return materials


def _view(doc: ProgramDoc) -> dict:
    # Сжатое представление программы (SPEC-JUDGE-03) плюс реальные материалы модулей (SPEC-JUDGE-07):
    # замечания судьи привязываются к узлам графа, а ответ укладывается в лимит токенов
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
             'topics': [f'{t.n} {t.title}' for t in m.topics],
             'материалы': _module_materials(doc, m)}
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
        'Ты — эксперт-методист, проверяешь программу дополнительного образования. '
        'Для каждого правила верни status pass или warn и 0–3 коротких конкретных замечания. '
        'В материалах каждого модуля — реальные вопросы (верным помечен вариант с ✓), задания с критериями, слайды и планы лекций. '
        'Проверяй их по существу: ключ вопроса должен указывать на действительно верный вариант (V-19), вопросы и слайды должны быть на русском (V-26). '
        'Замечание — только если нарушение явное; в начале замечания указывай id элемента в квадратных скобках, например [q1.2] или [sl1.1.3]. '
        'Не рассуждай вслух: ответ — сразу JSON до 300 токенов, без пояснений: {"verdicts": [{"rule": "V-21", "status": "pass", "messages": []}]}.'
    )
    user = json.dumps({'rules': RULES, 'program': _view(doc)}, ensure_ascii=False)
    try:
        out: JudgeOut = await llm.complete_json(
            skill='judge', role='judge', system=system, user=user, schema=JudgeOut, temperature=0.0, max_tokens=4096, stats=stats,
        )
    except LLMUnavailable as exc:  # без судьи остаются оценки кода
        logging.getLogger(__name__).warning('judge program=%s: судья недоступен: %s', doc.id, str(exc)[:200])
        if stats is not None:
            stats.fallback('judge', exc, 'оценки правил кодом без судьи')
        return []
    doc.kit.judge = {}
    for v in out.verdicts:
        msgs = [m.strip() for m in v.messages[:3] if m.strip()]
        if v.rule in RULES and v.status == 'warn' and msgs:
            tag = f'[{v.node.strip()}] ' if v.node.strip() else ''
            doc.kit.judge[v.rule] = [tag + m for m in msgs]
    return [f'{k}: {v[0]}' for k, v in doc.kit.judge.items()]


def _nodes_of(msgs: list[str]) -> list[str]:
    nodes: list[str] = []
    for m in msgs:
        found = _NODE_RX.match(m)
        if found and found.group(1) not in nodes:
            nodes.append(found.group(1))
    return nodes


def judge_rows(doc: ProgramDoc) -> list[RuleResult]:
    """Замечания судьи — отдельными строками отчёта (SPEC-JUDGE-08): формальные правила кода
    и содержательные замечания судьи показываются раздельно; узлы берутся из пометок [узел]."""
    from app.validation.rules import RULES as CODE_RULES

    titles = {r.id: r.title for r in CODE_RULES}
    rows = []
    for rid, msgs in doc.kit.judge.items():
        if rid not in RULES or not msgs:
            continue
        rows.append(RuleResult(
            id=f'{rid}-judge', title=f'Судья: {titles.get(rid, rid)}', check=None, kind='llm',
            status='warn', messages=msgs[:3], nodes=_nodes_of(msgs)[:10],
        ))
    return rows


def merge(doc: ProgramDoc, report: Report) -> None:
    """Вариант свёртки для прямых вызовов: замечания судьи добавляются в строки правил с узлами.
    Отчёт комплекта собирает их раздельно через judge_rows (SPEC-JUDGE-08)."""
    for rule in report.rules:
        msgs = doc.kit.judge.get(rule.id)
        if msgs:
            rule.status = 'warn' if rule.status == 'pass' else rule.status
            rule.messages += [f'Судья: {m}' for m in msgs]
            for node in _nodes_of(msgs):
                if node not in rule.nodes:
                    rule.nodes.append(node)
