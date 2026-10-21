"""Навык repair: детерминированные исправления элементов, не прошедших правило (FR-34).

Не больше 2 попыток на элемент; оставшиеся ошибки показываются методисту.
"""

from __future__ import annotations

import re
import zlib

from app.programs.schemas import (
    Assessment,
    Criterion,
    ProgramDoc,
    Question_,
    RuleResult,
    Slide,
    Task,
)
from app.validation.rules import assessment_map

_KEY_RX = re.compile(r'\b(?:правильный|верный)?\s*ответ\s*[:—–-]\s*(.+)', re.I)


def _key_from_text(q: Question_) -> int:
    """Ключ восстанавливается по тексту вопроса только при однозначной метке верного ответа (F09)."""
    for m in _KEY_RX.finditer(q.stem):
        marked = m.group(1).strip().strip('«»"').rstrip('.!').strip().lower()
        hits = [i for i, o in enumerate(q.options) if o.strip().lower() == marked]
        if len(hits) == 1:
            return hits[0]
    return -1


def _extend_task_for_lo(t: Task, lo_text: str, log: list[str]) -> None:
    """Ро добавляется заданию только вместе с формулировкой и критериями под этот РО (F10):
    голая привязка lo_ids давала формальное покрытие без содержания."""
    changed = False
    known = ' '.join([t.statement, t.expected_result, *(c.text for c in t.criteria)]).lower()
    if lo_text.lower() not in known:
        task_part = f'Выполните практическое задание: {lo_text} — распишите шаги, инструменты и результат.'
        t.statement = f'{t.statement.rstrip(". ")}; {task_part}' if t.statement.strip() else task_part
        if not t.expected_result.strip():
            t.expected_result = f'Выполненное практическое задание: {lo_text}'
        changed = True
    if not any(lo_text.lower() in c.text.lower() for c in t.criteria):
        t.criteria += [
            Criterion(text=f'Шаги практического задания по «{lo_text}» выполнены, результат соответствует требованию', points=4),
            Criterion(text=f'Ход и результат работы по «{lo_text}» воспроизводимы и оформлены', points=2),
        ]
        changed = True
    if changed:
        log.append(f'Задание «{t.title}»: формулировка и критерии дополнены под РО «{lo_text}»')


def repair(doc: ProgramDoc, rules: list[RuleResult]) -> list[str]:
    """Чинит то, что можно починить кодом, и возвращает журнал исправлений."""
    log: list[str] = []
    failed = {r.id for r in rules if r.status == 'fail'}
    lo_ids = {lo.id for lo in doc.all_outcomes()}
    if 'V-19' in failed:
        for q in doc.kit.questions:
            right = q.options[q.key].strip() if 0 <= q.key < len(q.options) else None
            uniq = list(dict.fromkeys(o.strip() for o in q.options))
            if len(uniq) != len(q.options):
                if right is not None:
                    q.key = uniq.index(right)
                while len(uniq) < 4:
                    uniq.append(f'Другой вариант {len(uniq) + 1}')
                q.options = uniq
                log.append(f'Вопрос {q.id}: убраны повторяющиеся варианты')
            if not 0 <= q.key < len(q.options):
                restored = _key_from_text(q)
                if restored >= 0:
                    q.key = restored
                    log.append(f'Вопрос {q.id}: ключ восстановлен по тексту вопроса')
                else:
                    # F09: ключ не подменяется нулём — дефект остаётся видимым для V-19 и методиста
                    log.append(f'Вопрос {q.id}: ключ {q.key} вне диапазона вариантов и по тексту не восстанавливается — нужна вычитка эксперта')
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
                valid = [pool[zlib.crc32(q.id.encode()) % len(pool)]] if pool else []
                log.append(f'Вопрос {q.id}: привязан к РО по теме модуля')
            q.lo_ids = valid
    if 'V-13' in failed or 'V-14' in failed:
        amap = assessment_map(doc)
        los = {lo.id: lo for lo in doc.all_outcomes()}
        final = next((t for t in doc.kit.tasks if t.assessment_id == 'final'), None)
        for lo_id, means in amap.items():
            if len(means) >= 2 or final is None or lo_id in final.lo_ids:
                continue
            if lo_id not in los:
                log.append(f'{lo_id}: покрытие требует эксперта — РО не найден в программе')
                continue
            final.lo_ids.append(lo_id)
            _extend_task_for_lo(final, los[lo_id].text, log)
            log.append(f'{lo_id}: добавлен в критерии итоговой аттестации')
        log += cover_outcomes(doc)
    if 'V-09' in failed:
        log += _fix_materials(doc)
    if 'V-17' in failed:
        log += _drop_reference_overlap(doc)
    if failed & {'V-08', 'V-11'}:
        # Разделы шаблона собираются кодом из графа: пересборка заполняет пропуски и возвращает пустые поля реквизитов
        from app.agent.sections import build_sections

        doc.kit.sections = build_sections(doc)
        log.append('Разделы шаблона пересобраны: пустые разделы заполнены, реквизиты и ФИО оставлены полями')
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
                _extend_task_for_lo(sem, los[lo_id].text, log)
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


def _fix_materials(doc: ProgramDoc) -> list[str]:
    """V-09: тема лекции совпадает с темой УТП; слайды есть у модулей из запроса (или хотя бы у одного)."""
    log = []
    titles = {t.id: t.title for t in doc.all_topics()}
    for lec in doc.kit.lectures:
        if lec.topic_id in titles and lec.title.strip().lower() != titles[lec.topic_id].strip().lower():
            lec.title = titles[lec.topic_id]
            log.append(f'Лекция {lec.id}: тема приведена к УТП')
    wanted = [m for m in doc.modules if m.n in doc.params.materials.slides_modules]
    if not any(lec.slides for lec in doc.kit.lectures) and not wanted and doc.modules:
        wanted = [doc.modules[0]]
    for m in wanted:
        if any(lec.module_id == m.id and lec.slides for lec in doc.kit.lectures):
            continue
        for lec in [x for x in doc.kit.lectures if x.module_id == m.id]:
            topic = next((t for t in m.topics if t.id == lec.topic_id), None)
            points = [s.strip() for s in re.split(r'(?<=[.!?])\s+', topic.description if topic else '') if s.strip()][:4]
            lec.slides = [
                Slide(id=f'{lec.id}-s1', n=1, title=lec.title, bullets=points[:2] or [lec.title]),
                *[Slide(id=f'{lec.id}-s{i + 2}', n=i + 2, title=str(step.get('text', ''))[:80], bullets=[str(step.get('text', ''))]) for i, step in enumerate(lec.plan[:3])],
            ]
        log.append(f'Модуль {m.n}: слайды собраны по плану лекций и темам УТП — нужна вычитка эксперта')
    return log


def _drop_reference_overlap(doc: ProgramDoc) -> list[str]:
    """V-17: предложения, совпадающие с референсом по 8-граммам, убираются из аннотаций и текстов тем."""
    from app.validation.ngrams import _tokens, ngrams

    ref = ngrams(_tokens(' '.join(r.text_sample for r in doc.references)))
    if not ref:
        return []

    def clean(text: str) -> tuple[str, int]:
        parts = re.split(r'(?<=[.!?])\s+', text)
        kept = [x for x in parts if not (ngrams(_tokens(x)) & ref)]
        return ' '.join(kept), len(parts) - len(kept)

    removed = 0
    for mp in doc.kit.module_programs:
        mp.annotation, n = clean(mp.annotation)
        removed += n
        for item in mp.content:
            item['text'], n = clean(item.get('text', ''))
            removed += n
    for t in doc.all_topics():
        t.description, n = clean(t.description)
        removed += n
    return [f'Убрано {removed} предложений, совпавших с референсом'] if removed else []
