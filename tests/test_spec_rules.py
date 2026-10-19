"""Спецификация specs/validation-rules.md: правила V-01…V-27 и отчёт агента (FR-32 – FR-35)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import (  # noqa: E402
    Assessment,
    Calendar,
    CalendarOption,
    Competency,
    Criterion,
    FinalAssessment,
    Hours,
    Indicator,
    LearningOutcome,
    Lecture,
    Materials,
    Module,
    Params,
    ProfStandard,
    ProgramDoc,
    ProgramType,
    Question_,
    ReferenceInfo,
    Slide,
    Source,
    Task,
    Topic,
)
from app.validation import rules as R  # noqa: E402
from app.validation.ngrams import _tokens, overlap_share  # noqa: E402
from app.validation.report import build_report, coverage  # noqa: E402


def _doc(**kw) -> ProgramDoc:
    """Сходящийся каркас ДПП ПК на 36 ч: 2 модуля, 3 РО, у каждого РО — тема и два плановых средства."""
    los = [LearningOutcome(id=f'lo{i}', code=f'РО {i}', text=t) for i, t in enumerate(['Пишет циклы', 'Пишет функции', 'Читает файлы'], 1)]
    base = dict(
        id='p', request='x', title='Python', type=ProgramType.DPP_PK, volume_h=36, goal='Цель',
        competencies=[Competency(id='c1', code='ПК-1', title='К', indicators=[Indicator(id='i1', kind='can', text='x', outcomes=los)])],
        modules=[
            Module(id='m1', n=1, title='Основы', hours=Hours(total=20, lk=6, pr=10, srs=4), topics=[
                Topic(id='t1.1', n='1.1', title='Циклы', hours=Hours(total=10, lk=3, pr=5, srs=2), lo_ids=['lo1']),
                Topic(id='t1.2', n='1.2', title='Функции', hours=Hours(total=10, lk=3, pr=5, srs=2), lo_ids=['lo2']),
            ]),
            Module(id='m2', n=2, title='Файлы', hours=Hours(total=14, lk=4, pr=8, srs=2), topics=[
                Topic(id='t2.1', n='2.1', title='Работа с файлами', hours=Hours(total=14, lk=4, pr=8, srs=2), lo_ids=['lo3']),
            ]),
        ],
        final_assessment=FinalAssessment(form='Зачёт', hours=2),
    )
    base.update(kw)
    return ProgramDoc(**base)


def _status(doc: ProgramDoc, rule_id: str, stage: str = 'kit') -> str:
    return {r.id: r.status for r in R.run_rules(doc, stage)}[rule_id]


def _check_of(rule_id: str) -> int | None:
    return next(r.check for r in R.RULES if r.id == rule_id)


def test_27_rules_kinds() -> None:
    """SPEC-RULES-01: 27 правил V-01…V-27; V-21, V-22, V-26, V-27 — вида llm, остальные — code."""
    assert [r.id for r in R.RULES] == [f'V-{i:02d}' for i in range(1, 28)]
    assert {r.id for r in R.RULES if r.kind == 'llm'} == {'V-21', 'V-22', 'V-26', 'V-27'}
    assert all(r.kind == 'code' for r in R.RULES if r.id not in {'V-21', 'V-22', 'V-26', 'V-27'})


def test_stage_rule_sets() -> None:
    """SPEC-RULES-02: каркас проверяется 15 правилами этапа skeleton, комплект — всеми 27."""
    doc = _doc()
    sk = [r.id for r in R.run_rules(doc, 'skeleton')]
    assert sk == ['V-01', 'V-02', 'V-03', 'V-04', 'V-05', 'V-06', 'V-07', 'V-08', 'V-10', 'V-12', 'V-13', 'V-15', 'V-21', 'V-22', 'V-27']
    assert len(R.run_rules(doc, 'kit')) == 27


def test_fail_downgraded_and_exception_isolated(monkeypatch) -> None:
    """SPEC-RULES-03: fail правила без блокирующей проверки понижается до warn; исключение правила даёт warn «Правило не выполнено»."""
    v25 = next(r for r in R.RULES if r.id == 'V-25')
    v01 = next(r for r in R.RULES if r.id == 'V-01')

    def boom(doc, stage):
        raise RuntimeError('x')

    monkeypatch.setattr(v25, 'fn', lambda doc, stage: ('fail', ['плохо'], []))
    monkeypatch.setattr(v01, 'fn', boom)
    res = {r.id: r for r in R.run_rules(_doc(), 'kit')}
    assert res['V-25'].status == 'warn'
    assert res['V-01'].status == 'warn' and res['V-01'].messages == ['Правило не выполнено: RuntimeError']
    assert len(res) == 27


def test_v05_v06_v07_hours_rules() -> None:
    """SPEC-RULES-06: V-05 (контактная работа в тексте), V-06 (аудиторные часы стажировки), V-07 (минимум практики, 40 % для ДПП ПК) — fail проверки 1."""
    assert {_check_of(x) for x in ('V-05', 'V-06', 'V-07')} == {1}
    doc = _doc()
    doc.kit.sections['volume'] = 'Объём 36 ч, из них контактная работа — 28 ч.'
    assert _status(doc, 'V-05') == 'pass'
    doc.kit.sections['volume'] = 'Объём 36 ч, из них контактная работа — 20 ч.'
    assert _status(doc, 'V-05') == 'fail'
    assert _status(doc, 'V-05', 'skeleton') == 'pass'  # текста разделов на каркасе ещё нет

    assert _status(_doc(type=ProgramType.DPP_PK_INTERNSHIP), 'V-06') == 'fail'
    intern = _doc(type=ProgramType.DPP_PK_INTERNSHIP)
    for m in intern.modules:
        m.hours = Hours(total=m.hours.total, srs=m.hours.total)
        for t in m.topics:
            t.hours = Hours(total=t.hours.total, srs=t.hours.total)
    assert _status(intern, 'V-06') == 'pass'

    assert _status(_doc(), 'V-07') == 'pass'  # практика 18 из 28 аудиторных
    assert _status(_doc(min_practice_hours=20), 'V-07') == 'fail'
    low = _doc()
    low.modules[1].hours = Hours(total=14, lk=12, srs=2)
    low.modules[1].topics[0].hours = Hours(total=14, lk=12, srs=2)
    assert _status(low, 'V-07') == 'fail'  # 10 ч практики из 28 аудиторных < 40 %
    assert _status(low.model_copy(update={'type': ProgramType.DOOP}), 'V-07') == 'pass'


def test_v08_v09_completeness() -> None:
    """SPEC-RULES-07: пустой раздел шаблона или элемент каркаса (V-08) и нет материалов из запроса (V-09) — fail проверки 2."""
    assert _check_of('V-08') == _check_of('V-09') == 2
    assert _status(_doc(), 'V-08', 'skeleton') == 'pass'
    assert _status(_doc(goal=''), 'V-08', 'skeleton') == 'fail'
    doc = _doc()
    for key, _title, _lvl in R.SECTIONS_DPP:
        doc.kit.sections[key] = 'текст'
    assert _status(doc, 'V-08') == 'pass'
    doc.kit.sections['goal'] = '  '
    res = next(r for r in R.run_rules(doc, 'kit') if r.id == 'V-08')
    assert res.status == 'fail' and res.nodes == ['section:1.2. Цель реализации программы']

    doc = _doc(params=Params(materials=Materials(test_questions=2, slides_modules=[1])))
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1.1', module_id='m1', title='Циклы', slides=[Slide(id='s', n=1, title='x')])]
    doc.kit.questions = [Question_(id=f'q{i}', assessment_id='test-final', stem='?', options=['a', 'b'], key=0, lo_ids=['lo1']) for i in range(2)]
    assert _status(doc, 'V-09') == 'pass'
    doc.kit.questions.pop()
    assert _status(doc, 'V-09') == 'fail'  # в запросе 2 вопроса, в тесте 1
    doc = _doc(params=Params(materials=Materials(slides_modules=[2])))
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1.1', module_id='m1', title='Циклы', slides=[Slide(id='s', n=1, title='x')])]
    assert _status(doc, 'V-09') == 'fail'  # нет слайдов для модуля 2


def test_v10_calendar() -> None:
    """SPEC-RULES-08: пока конфликт календаря не решён или нагрузка выше ограничения (V-10) — fail проверки 3."""
    assert _check_of('V-10') == 3
    opts = [CalendarOption(id='extend', title='Увеличить срок', weeks=4, hours_per_day=4, days_per_week=5)]
    doc = _doc(calendar=Calendar(hours_per_day=4, conflict='Не укладывается', options=opts))
    assert _status(doc, 'V-10') == 'fail'
    doc.calendar.chosen_option = 'extend'
    assert _status(doc, 'V-10') == 'warn'
    assert _status(_doc(calendar=Calendar(hours_per_day=8), params=Params(max_hours_per_day=6)), 'V-10') == 'fail'
    assert _status(_doc(calendar=Calendar(hours_per_day=6), params=Params(max_hours_per_day=6)), 'V-10') == 'pass'


@pytest.mark.parametrize(
    ('text', 'status'),
    [
        ('Утверждено приказом № ________________ от ________________', 'pass'),
        ('Утверждено приказом № 15-к', 'fail'),
        ('Дата приказа от «12» мая', 'fail'),
        ('Составитель: Иванов И. И.', 'fail'),
    ],
)
def test_v11_human_fields(text: str, status: str) -> None:
    """SPEC-RULES-09: заполненные номер приказа, дата или ФИО в реквизитах (V-11) — fail проверки 4."""
    assert _check_of('V-11') == 4
    doc = _doc()
    doc.kit.sections['approval'] = text
    assert _status(doc, 'V-11') == status


def test_v11_staff_section() -> None:
    """SPEC-RULES-09: ФИО преподавателя, вписанное в раздел «Кадровое обеспечение» (3.4), тоже даёт fail V-11."""
    doc = _doc()
    doc.kit.sections['conditions_org'] = 'Состав преподавателей (ФИО, должность, модули): ________________.'
    assert _status(doc, 'V-11') == 'pass'
    doc.kit.sections['conditions_org'] = 'Состав преподавателей: Иванов И. И., доцент, модули 1–3.'
    assert _status(doc, 'V-11') == 'fail'


def test_v12_v13_coverage() -> None:
    """SPEC-RULES-10: РО не раскрыт ни в одной теме (V-12) или проверяется меньше чем двумя средствами (V-13) — fail проверки 5."""
    assert _check_of('V-12') == _check_of('V-13') == 5
    doc = _doc()
    assert _status(doc, 'V-12', 'skeleton') == 'pass' and _status(doc, 'V-13', 'skeleton') == 'pass'
    doc.modules[1].topics[0].lo_ids = []
    assert _status(doc, 'V-12', 'skeleton') == 'fail'
    doc = _doc()
    doc.kit.questions = [Question_(id='q1', assessment_id='test-m1', stem='?', options=['a', 'b'], key=0, lo_ids=['lo1', 'lo2', 'lo3'])]
    doc.kit.tasks = [Task(id='k1', assessment_id='sem-m1', title='З', statement='с', lo_ids=['lo1', 'lo2'])]
    res = next(r for r in R.run_rules(doc, 'kit') if r.id == 'V-13')
    assert res.status == 'fail' and res.nodes == ['lo3']


def test_v14_binding() -> None:
    """SPEC-RULES-11: вопрос или задание без привязки к существующему РО (V-14) — fail проверки 6."""
    assert _check_of('V-14') == 6
    doc = _doc()
    doc.kit.questions = [Question_(id='q1', assessment_id='a', stem='?', options=['a', 'b'], key=0, lo_ids=['lo1'])]
    assert _status(doc, 'V-14') == 'pass'
    doc.kit.questions.append(Question_(id='q2', assessment_id='a', stem='?', options=['a', 'b'], key=0, lo_ids=['lo99']))
    doc.kit.tasks = [Task(id='k1', assessment_id='a', title='З', statement='с')]
    res = next(r for r in R.run_rules(doc, 'kit') if r.id == 'V-14')
    assert res.status == 'fail' and res.nodes == ['q2', 'k1']


def test_v15_v16_sources() -> None:
    """SPEC-RULES-12: ПС или ТФ не из реестра, ПС у ДООП (V-15), источник не в реестре и не помечен (V-16) — fail проверки 7."""
    from app.kb.registry import registry

    assert _check_of('V-15') == _check_of('V-16') == 7
    ps = registry()['ps'][0]
    tf = ps['tf'][0]['code']
    good = ProfStandard(code=ps['code'], title=ps['title'], order='', confirmed=True)
    doc = _doc(profstandard=good)
    doc.competencies[0].tf_codes = [tf]
    assert _status(doc, 'V-15') == 'pass'
    doc.competencies[0].tf_codes = ['Z/99.9']
    assert _status(doc, 'V-15') == 'fail'
    assert _status(_doc(), 'V-15') == 'fail'  # ДПП ПК без ПС
    assert _status(_doc(profstandard=ProfStandard(code='99.999', title='x', order='')), 'V-15') == 'fail'
    assert _status(_doc(type=ProgramType.DOOP, profstandard=good), 'V-15') == 'fail'
    assert _status(_doc(type=ProgramType.DOOP), 'V-15') == 'pass'

    src = [Source(id='s1', kind='url', bibl='Документация Python 3 — https://docs.python.org/3/')]
    assert _status(_doc(sources=src), 'V-16') == 'pass'
    bad = [Source(id='s2', kind='book', bibl='Неизвестный А. Тайная книга о квазарах. 2024')]
    assert _status(_doc(sources=bad), 'V-16') == 'fail'
    marked = [Source(id='s2', kind='book', bibl='Неизвестный А. Тайная книга о квазарах. 2024 [не подтверждено]')]
    assert _status(_doc(sources=marked), 'V-16') == 'warn'


def test_v17_originality() -> None:
    """SPEC-RULES-13: доля совпадающих с референсом 8-грамм содержания не меньше 5 % (V-17) — fail проверки 8."""
    assert _check_of('V-17') == 8
    ref = 'Цикл for перебирает элементы последовательности по одному и выполняет тело цикла для каждого элемента списка'
    doc = _doc(references=[ReferenceInfo(name='r', text_sample=ref)])
    doc.kit.sections['content'] = 'Совершенно другой текст про функции, аргументы, возвращаемые значения и области видимости переменных в языке.'
    assert _status(doc, 'V-17') == 'pass'
    doc.kit.sections['content'] = ref
    assert _status(doc, 'V-17') == 'fail'
    # Обязательные формулы шаблона в сравнении не участвуют
    doc.kit.sections = {'audience': ref}
    assert _status(doc, 'V-17') == 'pass'


def test_v18_v19_measurability() -> None:
    """SPEC-RULES-14: задание без критериев с баллами > 0 (V-18), ключ вне вариантов или повтор вариантов (V-19) — fail проверки 9."""
    assert _check_of('V-18') == _check_of('V-19') == 9
    doc = _doc()
    doc.kit.tasks = [Task(id='k1', assessment_id='a', title='З', statement='с', criteria=[Criterion(text='ok', points=5)])]
    doc.kit.questions = [Question_(id='q1', assessment_id='a', stem='?', options=['a', 'b'], key=1)]
    assert _status(doc, 'V-18') == 'pass' and _status(doc, 'V-19') == 'pass'
    doc.kit.tasks.append(Task(id='k2', assessment_id='a', title='Без баллов', statement='с', criteria=[Criterion(text='x', points=0)]))
    doc.kit.tasks.append(Task(id='k3', assessment_id='a', title='Без критериев', statement='с'))
    doc.kit.questions += [
        Question_(id='q2', assessment_id='a', stem='?', options=['a', 'b'], key=2),
        Question_(id='q3', assessment_id='a', stem='?', options=['a', 'A '], key=0),
    ]
    res = {r.id: r for r in R.run_rules(doc, 'kit')}
    assert res['V-18'].status == 'fail' and res['V-18'].nodes == ['k2', 'k3']
    assert res['V-19'].status == 'fail' and res['V-19'].nodes == ['q2', 'q3']


def test_warning_only_rules(monkeypatch) -> None:
    """SPEC-RULES-16: V-23 (устаревшие версии), V-24 (падающие примеры), V-25 (сходство тем > 0.85), V-26 (кириллица < 80 %), V-27 (обещания) дают только warn."""
    assert all(_check_of(x) is None for x in ('V-23', 'V-24', 'V-25', 'V-26', 'V-27'))
    doc = _doc(goal='Гарантируем, что слушатель будет полностью подготовлен')
    doc.modules[1].topics[0].title = 'Циклы'  # почти дубль темы 1.1 в другом модуле
    doc.modules[1].topics[0].description = 'Устанавливаем Python 2.7'
    doc.kit.sections['content'] = 'This section is written entirely in English without Russian words at all.'
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1.1', module_id='m1', title='Циклы', code_examples=['1/0'])]
    monkeypatch.setattr('app.validation.sandbox.check_examples', lambda d: ['Пример к лекции Циклы: ZeroDivisionError'])
    res = {r.id: r for r in R.run_rules(doc, 'kit')}
    for rid in ('V-23', 'V-24', 'V-25', 'V-26', 'V-27'):
        assert res[rid].status == 'warn', rid
    clean = {r.id: r.status for r in R.run_rules(_doc(), 'kit')}
    assert all(clean[x] == 'pass' for x in ('V-23', 'V-25', 'V-27'))


def test_coverage_matrix_planned_and_actual() -> None:
    """SPEC-RULES-18: матрица «РО × средство» на каркасе — по плановым средствам, на комплекте — по вопросам и заданиям."""
    doc = _doc()
    sk = {row['lo_id']: row for row in coverage(doc, 'skeleton')}
    assert set(sk) == {'lo1', 'lo2', 'lo3'}
    assert sk['lo1']['cells'] == {'Контроль М1': 1, 'Сем. М1': 1, 'ИА': 1} and sk['lo1']['means'] == 3
    assert sk['lo3']['topics'] == ['2.1']
    doc.kit.assessments = [Assessment(id='test-m1', module_id='m1', kind='test', title='Тест М1')]
    doc.kit.questions = [Question_(id=f'q{i}', assessment_id='test-m1', stem='?', options=['a', 'b'], key=0, lo_ids=['lo1']) for i in range(3)]
    doc.kit.tasks = [Task(id='k1', assessment_id='project', title='П', statement='с', lo_ids=['lo1', 'lo2'])]
    kit = {row['lo_id']: row for row in coverage(doc, 'kit')}
    assert kit['lo1']['cells'] == {'Тест М1': 3, 'project': 1} and kit['lo1']['means'] == 2
    assert kit['lo3']['cells'] == {} and kit['lo3']['means'] == 0
    assert build_report(doc, 'kit').coverage == coverage(doc, 'kit')


def test_originality_by_8grams() -> None:
    """SPEC-RULES-19: оригинальность — доля 8-грамм текста (латиница, кириллица, цифры в нижнем регистре), встречающихся в референсе."""
    assert _tokens('Цикл FOR, v2 — ёлка!') == ['цикл', 'for', 'v2', 'ёлка']
    ref = 'один два три четыре пять шесть семь восемь'
    assert overlap_share('ОДИН, два; три четыре пять шесть семь восемь', ref) == 1.0
    # 3 восьмиграммы текста, одна из них есть в референсе
    assert overlap_share(ref + ' девять десять', ref) == pytest.approx(1 / 3)
    assert overlap_share('коротко', ref) == 0.0
