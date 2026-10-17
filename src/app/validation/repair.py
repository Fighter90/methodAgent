"""Навык repair: детерминированные исправления элементов, не прошедших правило (FR-34).

Не больше 2 попыток на элемент; оставшиеся ошибки показываются методисту.
"""

from __future__ import annotations

from app.programs.schemas import (
    Assessment,
    Criterion,
    ProgramDoc,
    Question_,
    RuleResult,
)
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
        log += cover_outcomes(doc)
    if 'V-16' in failed:
        for s in doc.sources:
            if not s.confirmed and 'не подтверждено' not in s.bibl:
                s.bibl = f'{s.bibl} [не подтверждено]'
                log.append(f'Источник {s.id} помечен «не подтверждено»')
    return log


def cover_outcomes(doc: ProgramDoc) -> list[str]:
    """V-13: РО, который проверяется одним средством, получает вопрос в тесте своего модуля.

    Верный ответ — формулировка РО, дистракторы — РО других модулей: вопрос проверяет,
    что слушатель отличает результат темы от соседних.
    """
    log: list[str] = []
    amap = assessment_map(doc)
    los = {lo.id: lo for lo in doc.all_outcomes()}
    final_test = any(a.id == 'test-final' for a in doc.kit.assessments)
    for lo_id, means in amap.items():
        if len(means) >= 2 or lo_id not in los:
            continue
        m = next((m for m in doc.modules for t in m.topics if lo_id in t.lo_ids), None)
        if m is None:
            continue
        topic = next(t for t in m.topics if lo_id in t.lo_ids)
        test_id = 'test-final' if final_test else f'test-{m.id}'
        if test_id in means:
            sem = next((t for t in doc.kit.tasks if t.module_id == m.id and t.assessment_id.startswith('sem-')), None)
            if sem is not None and lo_id not in sem.lo_ids:
                sem.lo_ids.append(lo_id)
                log.append(f'{los[lo_id].code}: добавлен в задание «{sem.title}»')
            continue
        own = {x for t in m.topics for x in t.lo_ids}
        foreign = [lo.text for lo in doc.all_outcomes() if lo.id not in own] or [t.title for mm in doc.modules if mm.id != m.id for t in mm.topics]
        foreign = [f for f in dict.fromkeys(foreign) if f != los[lo_id].text]
        while len(foreign) < 3:
            foreign.append(f'Не относится к модулю «{m.title}» (вариант {len(foreign) + 1})')
        n = sum(1 for q in doc.kit.questions if q.module_id == m.id) + 1
        shift = (n * 3) % len(foreign)
        options = [los[lo_id].text, *(foreign[(shift + j) % len(foreign)] for j in range(3))]
        key = n % 4
        options[0], options[key] = options[key], options[0]
        q = Question_(
            id='', assessment_id=test_id, module_id=m.id,
            stem=f'Что слушатель должен уметь после темы «{topic.title}»?', options=options, key=key, lo_ids=[lo_id],
        )
        # Объём теста задан в запросе — вопрос заменяет один из вопросов по РО, который проверяется несколькими вопросами
        spare = _spare_question(doc, test_id, m.id) if doc.params.materials.test_questions else None
        if spare is not None:
            q.id = spare.id
            doc.kit.questions[doc.kit.questions.index(spare)] = q
        else:
            ids = {x.id for x in doc.kit.questions}
            q.id = next(c for c in (f'qf.{i}' if final_test else f'q{m.n}.{i}' for i in range(n, n + 200)) if c not in ids)
            doc.kit.questions.append(q)
        if not any(a.id == test_id for a in doc.kit.assessments):
            doc.kit.assessments.append(Assessment(id=test_id, module_id=m.id, kind='test', title=f'Тест М{m.n}'))
        amap.setdefault(lo_id, set()).add(test_id)
        log.append(f'{los[lo_id].code}: добавлен вопрос в тест модуля {m.n}')
    return log


def _spare_question(doc: ProgramDoc, test_id: str, module_id: str) -> Question_ | None:
    per_lo: dict[str, int] = {}
    for q in doc.kit.questions:
        if q.assessment_id == test_id:
            for x in q.lo_ids:
                per_lo[x] = per_lo.get(x, 0) + 1
    pool = [q for q in doc.kit.questions if q.assessment_id == test_id and q.lo_ids and all(per_lo.get(x, 0) > 1 for x in q.lo_ids)]
    pool.sort(key=lambda q: (q.module_id != module_id, -min(per_lo[x] for x in q.lo_ids)))
    return pool[0] if pool else None
