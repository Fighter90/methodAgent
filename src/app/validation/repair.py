"""Навык repair: детерминированные исправления элементов, не прошедших правило (FR-34).

Не больше 2 попыток на элемент; оставшиеся ошибки показываются методисту.
"""

from __future__ import annotations

from app.programs.schemas import Criterion, ProgramDoc, RuleResult
from app.validation.rules import assessment_map


def repair(doc: ProgramDoc, rules: list[RuleResult]) -> list[str]:
    """Чинит то, что можно починить кодом, и возвращает журнал исправлений."""
    log: list[str] = []
    failed = {r.id for r in rules if r.status == 'fail'}
    lo_ids = {lo.id for lo in doc.all_outcomes()}
    if 'V-19' in failed:
        for q in doc.kit.questions:
            uniq = list(dict.fromkeys(o.strip() for o in q.options))
            if len(uniq) != len(q.options):
                while len(uniq) < 4:
                    uniq.append(f'Другой вариант {len(uniq) + 1}')
                q.options = uniq
                log.append(f'Вопрос {q.id}: убраны повторяющиеся варианты')
            if not 0 <= q.key < len(q.options):
                q.key = 0
                log.append(f'Вопрос {q.id}: ключ исправлен')
    if 'V-18' in failed:
        for t in doc.kit.tasks:
            if not t.criteria or any(c.points <= 0 for c in t.criteria):
                t.criteria = [Criterion(text='Задание выполнено полностью', points=4), Criterion(text='Решение корректно', points=4), Criterion(text='Результат оформлен', points=2)]
                log.append(f'{t.title}: добавлена рубрика')
    if 'V-14' in failed:
        topic_lo = {t.id: t.lo_ids for t in doc.all_topics()}
        for t in doc.kit.tasks:
            t.lo_ids = [x for x in t.lo_ids if x in lo_ids] or list(topic_lo.get(t.topic_id or '', []))
        module_lo = {m.id: [x for tp in m.topics for x in tp.lo_ids] for m in doc.modules}
        for q in doc.kit.questions:
            valid = [x for x in q.lo_ids if x in lo_ids]
            if not valid:
                pool = module_lo.get(q.module_id or '', []) or list(lo_ids)
                valid = [pool[hash(q.id) % len(pool)]] if pool else []
                log.append(f'Вопрос {q.id}: привязан к РО по теме модуля')
            q.lo_ids = valid
    if 'V-13' in failed or 'V-14' in failed:
        amap = assessment_map(doc)
        final = next((t for t in doc.kit.tasks if t.assessment_id == 'final'), None)
        for lo_id, means in amap.items():
            if len(means) < 2 and final is not None and lo_id not in final.lo_ids:
                final.lo_ids.append(lo_id)
                log.append(f'{lo_id}: добавлен в критерии итоговой аттестации')
    if 'V-16' in failed:
        for s in doc.sources:
            if not s.confirmed and 'не подтверждено' not in s.bibl:
                s.bibl = f'{s.bibl} [не подтверждено]'
                log.append(f'Источник {s.id} помечен «не подтверждено»')
    return log
