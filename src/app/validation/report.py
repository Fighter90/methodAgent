"""Отчёт автопроверки: правила, 10 блокирующих проверок, матрица покрытия, действия методиста."""

from __future__ import annotations

from app.programs.schemas import ProgramDoc, Report, RuleResult
from app.validation.rules import CHECK_TITLES, assessment_map, planned_assessment_map, run_rules


def blocking_status(rules: list[RuleResult]) -> dict[int, bool]:
    status = {}
    for n in CHECK_TITLES:
        related = [r for r in rules if r.check == n]
        status[n] = all(r.status != 'fail' for r in related)
    return status


def assessment_titles(doc: ProgramDoc) -> dict[str, str]:
    titles = {a.id: a.title for a in doc.kit.assessments}
    for m in doc.modules:
        titles.setdefault(f'ctrl-{m.id}', f'Контроль М{m.n}')
        titles.setdefault(f'sem-{m.id}', f'Сем. М{m.n}')
    titles.setdefault('final', 'ИА')
    return titles


def coverage(doc: ProgramDoc, stage: str) -> list[dict]:
    """Матрица «РО × средство оценивания»: число элементов средства, проверяющих РО."""
    rows = []
    titles = assessment_titles(doc)
    counts: dict[str, dict[str, int]] = {}
    if stage == 'kit':
        for q in doc.kit.questions:
            for lo_id in q.lo_ids:
                counts.setdefault(lo_id, {}).setdefault(q.assessment_id, 0)
                counts[lo_id][q.assessment_id] += 1
        for t in doc.kit.tasks:
            for lo_id in t.lo_ids:
                counts.setdefault(lo_id, {}).setdefault(t.assessment_id, 0)
                counts[lo_id][t.assessment_id] += 1
        amap = assessment_map(doc)
    else:
        amap = planned_assessment_map(doc)
        for lo_id, means in amap.items():
            counts[lo_id] = dict.fromkeys(means, 1)
    topics_by_lo: dict[str, list[str]] = {}
    for t in doc.all_topics():
        for lo_id in t.lo_ids:
            topics_by_lo.setdefault(lo_id, []).append(t.n)
    for c in doc.competencies:
        for ind in c.indicators:
            for lo in ind.outcomes:
                cells = counts.get(lo.id, {})
                rows.append(
                    {
                        'competency': c.code,
                        'lo_id': lo.id,
                        'lo': lo.code,
                        'text': lo.text,
                        'topics': topics_by_lo.get(lo.id, []),
                        'cells': {titles.get(k, k): v for k, v in cells.items()},
                        'means': len(amap.get(lo.id, set())),
                    }
                )
    return rows


def _proposal_for(rule: RuleResult, doc: ProgramDoc) -> list[dict]:
    out = []
    if rule.id == 'V-22':
        los = {lo.id: lo for lo in doc.all_outcomes()}
        for node in rule.nodes:
            lo = los.get(node)
            if lo:
                rest = lo.text.split(' ', 1)[1] if ' ' in lo.text else lo.text
                out.append({'rule_id': 'V-22', 'node': lo.id, 'title': f'{lo.code} «{lo.text}» нельзя проверить заданием', 'proposal': f'Объясняет и применяет на примере: {rest}'})
    elif rule.id == 'V-10' and doc.calendar.conflict and not doc.calendar.chosen_option:
        for opt in doc.calendar.options:
            out.append({'rule_id': 'V-10', 'node': 'calendar', 'title': doc.calendar.conflict, 'proposal': opt.title, 'option_id': opt.id})
    elif rule.id == 'V-27' and rule.messages:
        out.append({'rule_id': 'V-27', 'node': 'goal', 'title': rule.messages[-1], 'proposal': 'Сформулировать результаты как начальный уровень и показать разрыв заказчику в отчёте'})
    elif rule.id == 'V-15' and rule.status == 'warn':
        out.append({'rule_id': 'V-15', 'node': 'ps', 'title': rule.messages[0], 'proposal': 'Сверить коды ТФ с реестром Минтруда перед утверждением'})
    return out


def build_report(doc: ProgramDoc, stage: str) -> Report:
    rules = run_rules(doc, stage)
    blocking = blocking_status(rules)
    passed = sum(1 for n, ok in blocking.items() if ok and (stage == 'kit' or n in {1, 2, 3, 5, 7}))
    total = 10 if stage == 'kit' else 5
    actions = []
    for r in rules:
        if r.status == 'fail':
            actions.extend(r.messages[:3])
    for r in rules:
        if r.status == 'warn':
            actions.extend(r.messages[:2])
    proposals = [p for r in rules if r.status in ('warn', 'fail') for p in _proposal_for(r, doc)]
    decided = {(d.rule_id) for d in doc.decisions}
    for p in proposals:
        p['decided'] = p['rule_id'] in decided
    return Report(
        stage=stage,
        rules=rules,
        blocking_passed=passed,
        blocking_total=total,
        coverage=coverage(doc, stage),
        actions=actions[:20],
        proposals=proposals,
    )
