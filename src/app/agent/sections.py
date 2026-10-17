"""Разделы шаблона АЦР собираются кодом из графа комплекта — без копирования референса."""

from __future__ import annotations

from app.programs.schemas import ProgramDoc, ProgramType

BLANK = '________________'


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _join(items: list[str]) -> str:
    return '\n'.join(f'— {x};' for x in items[:-1]) + (f'\n— {items[-1]}.' if items else '')


def build_sections(doc: ProgramDoc) -> dict[str, str]:
    tot = doc.totals()
    p = doc.params
    doop = doc.type == ProgramType.DOOP
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP
    modules_list = [f'модуль {m.n} «{m.title}» ({m.hours.total} ч)' for m in doc.modules]
    s: dict[str, str] = {}
    s['annotation'] = (
        f'Программа «{doc.title}» ({doc.volume_h} ак. ч) предназначена для слушателей: {p.audience or "по профилю организации"}. '
        f'{doc.goal}. Программа включает {len(doc.modules)} модулей: {", ".join(modules_list)}. '
        f'Обучение завершается итоговой аттестацией в форме: {doc.final_assessment.form.lower()}.'
    )
    s['relevance'] = (
        f'Актуальность программы обусловлена спросом на практические навыки в области «{p.direction or doc.title}» '
        f'и необходимостью применять современные инструменты (версии актуальны на 2026 год).'
    )
    s['goal'] = f'Цель программы — {doc.goal[0].lower() + doc.goal[1:] if doc.goal else ""}.'
    res = []
    for c in doc.competencies:
        res.append(f'{c.code}. {c.title}' + (f' (ТФ {", ".join(c.tf_codes)} ПС {c.ps_code})' if c.tf_codes else ''))
        for ind in c.indicators:
            label = {'know': 'Знать', 'can': 'Уметь', 'own': 'Владеть'}[ind.kind]
            for lo in ind.outcomes:
                res.append(f'  {lo.code} ({label}): {lo.text}')
    s['results'] = '\n'.join(res)
    if doc.profstandard and not doop:
        ps = doc.profstandard
        tfs = '; '.join(f'{t.code} «{t.title}»' for t in ps.tf)
        s['ps'] = (
            f'Программа разработана с учётом профессионального стандарта {ps.code} «{ps.title}» ({ps.order}). '
            f'Трудовые функции: {tfs}.' + ('' if ps.confirmed else ' Коды трудовых функций требуют сверки с реестром Минтруда России.')
        )
    norm = '; '.join(src.bibl for src in doc.norm_base)
    s['audience'] = (
        f'{p.audience or "Слушатели по профилю организации"}. Входной уровень: {p.entry_level or "специальной подготовки не требуется"}.'
        + ('' if doop else ' К освоению допускаются лица, имеющие или получающие среднее профессиональное и (или) высшее образование.')
    )
    s['form'] = f'Форма обучения — {p.form or "очная"}.' + (' С применением электронного обучения и дистанционных образовательных технологий.' if p.distance else '')
    if internship:
        s['form'] += ' Стажировка проходит на рабочем месте под руководством наставника от организации; аудиторных занятий нет.'
    s['volume'] = (
        f'Трудоёмкость программы — {doc.volume_h} ак. ч, в том числе контактная работа {tot.contact} ч '
        f'(лекции {tot.lk} ч, практические занятия {tot.pr} ч, лабораторные {tot.lb} ч), '
        f'самостоятельная работа {tot.srs} ч, итоговая аттестация {doc.final_assessment.hours} ч. '
        f'Срок освоения — {doc.calendar.weeks} нед.'
    )
    cal = doc.calendar
    if cal.sessions:
        s['regime'] = f'Занятия {cal.days_per_week} раза в неделю по {cal.session_hours} ак. ч; всего {cal.sessions} занятий за {cal.weeks} нед.'
    else:
        s['regime'] = f'Не более {cal.hours_per_day} ак. ч в день, {cal.days_per_week} дней в неделю; {cal.work_days} {plural(cal.work_days, "учебный день", "учебных дня", "учебных дней")} за {cal.weeks} нед.'
    s['document'] = doc.issued_document + '.'
    s['curriculum'] = 'Учебный план приведён в таблице: модули, часы по видам работы, формы контроля и итоговая аттестация.'
    s['utp'] = 'Учебно-тематический план приведён в таблице: темы модулей с часами по видам работы.'
    s['calendar'] = 'Календарный учебный график: ' + '; '.join(f'неделя {w.week} — {w.hours} ч' for w in cal.schedule[:30]) + '.'
    s['content'] = '\n'.join(f'Модуль {m.n}. {m.title}: ' + '; '.join(f'тема {t.n} «{t.title}»' for t in m.topics) for m in doc.modules)
    s['conditions_org'] = (
        'Реализацию программы обеспечивают преподаватели и эксперты-практики с опытом работы в профильной области; '
        + ('руководитель стажировки от организации-партнёра; ' if internship else '')
        + 'методическое сопровождение осуществляет методический отдел.'
    )
    s['conditions_mt'] = 'Учебная аудитория или рабочее место с компьютером, доступ в интернет, установленное ПО по перечню модулей, электронная информационно-образовательная среда.'
    s['conditions_it'] = _join([src.bibl + (f' — URL: {src.url}' if src.url else '') for src in doc.sources]) or 'Перечень источников формируется.'
    controls = sorted({m.control for m in doc.modules})
    s['assessment'] = (
        f'Текущий контроль: {", ".join(controls).lower()}. Оценочные материалы: тесты с ключами, задания с критериями оценивания; '
        f'каждый результат обучения проверяется не менее чем двумя оценочными средствами (матрица покрытия в отчёте).'
    )
    s['final'] = f'Итоговая аттестация — {doc.final_assessment.form.lower()}, {doc.final_assessment.hours} ч. {doc.final_assessment.description}'
    s['competencies_list'] = '\n'.join(
        f'{c.code}. {c.title}' + (f' — трудовые функции {", ".join(c.tf_codes)}' if c.tf_codes else '') for c in doc.competencies
    )
    s['process'] = (
        'Образовательный процесс организуется по учебному плану и календарному учебному графику. '
        + ('Стажировка проходит на рабочем месте: слушатель выполняет задания по индивидуальному плану, наставник от организации '
           'консультирует и проводит собеседования по разделам; результаты фиксируются в отчёте о стажировке. ' if internship else
           'Занятия проводятся в форме лекций, практических и лабораторных работ; самостоятельная работа сопровождается консультациями. ')
        + ('Используются электронное обучение и дистанционные образовательные технологии. ' if p.distance else '')
        + 'Обучение ведётся на русском языке.'
    )
    s['methodical'] = (
        'Методические материалы: планы занятий с распределением времени, презентации к занятиям, практические задания с критериями, '
        'тест с ключами и рекомендации преподавателю по проведению занятий для обучающихся указанного возраста.'
    )
    s['quality'] = 'По окончании обучения проводится анкетирование слушателей для оценки удовлетворённости качеством программы.'
    s['assessment'] += ' ' + s['quality']
    s['authors'] = f'Составитель: {BLANK} (ФИО, должность). Утверждено приказом № {BLANK} от «__» ________ 20__ г. Подпись: {BLANK}.'
    s['norm'] = norm
    return s
