"""Спецификация specs/validation-repair.md: детерминированное автоисправление (FR-34)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import (  # noqa: E402
    Assessment,
    Competency,
    Criterion,
    Hours,
    Indicator,
    LearningOutcome,
    Lecture,
    Module,
    ModuleProgram,
    ProgramDoc,
    Question_,
    ReferenceInfo,
    RuleResult,
    Slide,
    Source,
    Task,
    Topic,
)
from app.validation.repair import _spare_question, cover_outcomes, repair  # noqa: E402
from app.validation.rules import assessment_map  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _lo(i: int, text: str) -> LearningOutcome:
    return LearningOutcome(id=f'lo{i}', code=f'РО {i}', text=text)


def _doc() -> ProgramDoc:
    return ProgramDoc(
        id='p', request='x', title='Python',
        competencies=[Competency(id='c1', code='ПК-1', title='К', indicators=[Indicator(id='i1', kind='can', text='x', outcomes=[
            _lo(1, 'Пишет циклы'), _lo(2, 'Пишет функции'), _lo(3, 'Читает файлы')])])],
        modules=[
            Module(id='m1', n=1, title='Основы', topics=[
                Topic(id='t1.1', n='1.1', title='Циклы', description='Цикл for перебирает элементы. Цикл while работает по условию.',
                      hours=Hours(total=4, lk=2, pr=2), lo_ids=['lo1']),
                Topic(id='t1.2', n='1.2', title='Функции', hours=Hours(total=2, lk=2), lo_ids=['lo2']),
            ]),
            Module(id='m2', n=2, title='Файлы', topics=[Topic(id='t2.1', n='2.1', title='Файлы', hours=Hours(total=2, pr=2), lo_ids=['lo3'])]),
        ],
    )


def _fail(*ids: str) -> list[RuleResult]:
    return [RuleResult(id=i, title='', check=None, kind='code', status='fail') for i in ids]


def test_no_failed_rules_no_changes() -> None:
    """SPEC-REPAIR-01: без правил в статусе fail документ не меняется и журнал пуст."""
    doc = _doc()
    doc.kit.questions = [Question_(id='q1', assessment_id='test-m1', stem='?', options=['a', 'a'], key=9)]
    before = doc.model_dump()
    rules = [RuleResult(id='V-19', title='', check=1, kind='code', status='pass')]
    assert repair(doc, rules) == []
    assert doc.model_dump() == before


def test_v19_duplicates_removed_and_key_fixed() -> None:
    """SPEC-REPAIR-02: V-19 — повторяющиеся варианты убираются, список добирается до 4, ключ вне диапазона становится 0."""
    doc = _doc()
    doc.kit.questions = [
        Question_(id='q1', assessment_id='test-m1', stem='?', options=['a', 'a ', 'b'], key=7),
        Question_(id='q2', assessment_id='test-m1', stem='?', options=['a', 'b', 'c', 'd'], key=1),
    ]
    log = repair(doc, _fail('V-19'))
    q1, q2 = doc.kit.questions
    assert q1.options == ['a', 'b', 'Другой вариант 3', 'Другой вариант 4'] and q1.key == 0
    assert q2.options == ['a', 'b', 'c', 'd'] and q2.key == 1
    assert 'Вопрос q1: убраны повторяющиеся варианты' in log and 'Вопрос q1: ключ исправлен' in log
    assert not any('q2' in x for x in log)


def test_v19_key_keeps_correct_answer() -> None:
    """SPEC-REPAIR-03: V-19 — после удаления повторов ключ указывает на тот же текст верного ответа."""
    doc = _doc()
    doc.kit.questions = [Question_(id='q1', assessment_id='test-m1', stem='?', options=['A', 'A', 'B', 'C'], key=2)]
    repair(doc, _fail('V-19'))
    q = doc.kit.questions[0]
    assert q.options[q.key] == 'B'


def test_v18_rubric_added() -> None:
    """SPEC-REPAIR-04: V-18 — задание без критериев или с неположительными баллами получает рубрику 4 + 4 + 2."""
    doc = _doc()
    good = [Criterion(text='ok', points=3)]
    doc.kit.tasks = [
        Task(id='t1', assessment_id='sem-m1', title='А', statement='s'),
        Task(id='t2', assessment_id='sem-m1', title='Б', statement='s', criteria=[Criterion(text='x', points=0)]),
        Task(id='t3', assessment_id='sem-m1', title='В', statement='s', criteria=good),
    ]
    log = repair(doc, _fail('V-18'))
    assert [c.points for c in doc.kit.tasks[0].criteria] == [4, 4, 2]
    assert [c.points for c in doc.kit.tasks[1].criteria] == [4, 4, 2]
    assert doc.kit.tasks[2].criteria == good
    assert log == ['А: добавлена рубрика', 'Б: добавлена рубрика']


def test_v14_bindings_to_existing_outcomes() -> None:
    """SPEC-REPAIR-05: V-14 — ссылки на несуществующие РО заменяются РО темы (задание) или РО модуля (вопрос)."""
    doc = _doc()
    doc.kit.tasks = [Task(id='t1', assessment_id='sem-m1', topic_id='t1.1', title='А', statement='s', lo_ids=['ghost'])]
    doc.kit.questions = [
        Question_(id='q1', assessment_id='test-m1', module_id='m1', stem='?', options=list('abcd'), key=0, lo_ids=['ghost']),
        Question_(id='q2', assessment_id='test-m2', module_id='m2', stem='?', options=list('abcd'), key=0, lo_ids=['lo3', 'ghost']),
    ]
    log = repair(doc, _fail('V-14'))
    assert doc.kit.tasks[0].lo_ids == ['lo1']
    assert doc.kit.questions[0].lo_ids[0] in {'lo1', 'lo2'}
    assert doc.kit.questions[1].lo_ids == ['lo3']
    assert 'Вопрос q1: привязан к РО по теме модуля' in log


def test_v14_choice_is_deterministic_across_processes() -> None:
    """SPEC-REPAIR-06: V-14 — выбор РО для вопроса без валидной привязки не зависит от процесса (детерминирован)."""
    code = (
        'import os; os.environ["LLM_PROVIDERS"]="fixtures"\n'
        'from app.programs.schemas import *\n'
        'from app.validation.repair import repair\n'
        'los=[LearningOutcome(id=f"lo{i}",code=f"РО {i}",text=f"т{i}") for i in range(7)]\n'
        'doc=ProgramDoc(id="p",request="x",competencies=[Competency(id="c",code="К",title="К",indicators=[Indicator(id="i",kind="can",text="x",outcomes=los)])],'
        'modules=[Module(id="m1",n=1,title="М",topics=[Topic(id="t",n="1.1",title="Т",lo_ids=[lo.id for lo in los])])])\n'
        'doc.kit.questions=[Question_(id=f"q{i}",assessment_id="t",module_id="m1",stem="?",options=list("abcd"),key=0,lo_ids=["x"]) for i in range(8)]\n'
        'repair(doc,[RuleResult(id="V-14",title="",check=None,kind="code",status="fail")])\n'
        'print([q.lo_ids[0] for q in doc.kit.questions])\n'
    )
    outs = set()
    for seed in ('1', '2'):
        env = {**os.environ, 'PYTHONHASHSEED': seed, 'PYTHONPATH': str(ROOT / 'src')}
        outs.add(subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, check=True).stdout)
    assert len(outs) == 1


def test_v13_final_and_question_cover_outcome() -> None:
    """SPEC-REPAIR-07: V-13 — РО, проверяемый менее чем двумя средствами, добавляется в итоговую аттестацию и получает вопрос в тесте модуля."""
    doc = _doc()
    doc.kit.tasks = [Task(id='fin', assessment_id='final', title='Итог', statement='s', lo_ids=[])]
    log = repair(doc, _fail('V-13'))
    amap = assessment_map(doc)
    assert all(len(v) >= 2 for v in amap.values())
    assert set(doc.kit.tasks[0].lo_ids) == {'lo1', 'lo2', 'lo3'}
    assert any('добавлен в критерии итоговой аттестации' in x for x in log)
    assert {a.id for a in doc.kit.assessments} >= {'test-m1', 'test-m2'}


def test_cover_outcomes_question_shape() -> None:
    """SPEC-REPAIR-08: добавленный вопрос имеет 4 варианта, верный ответ — формулировка РО по ключу, привязку к РО и уникальный id."""
    doc = _doc()
    log = cover_outcomes(doc)
    assert log
    ids = [q.id for q in doc.kit.questions]
    assert len(ids) == len(set(ids))
    for q in doc.kit.questions:
        lo = next(x for x in doc.all_outcomes() if x.id == q.lo_ids[0])
        assert len(q.options) == 4 and q.options[q.key] == lo.text
        assert q.assessment_id == f'test-{q.module_id}'


def test_cover_outcomes_final_test_and_seminar() -> None:
    """SPEC-REPAIR-09: при наличии итогового теста вопрос идёт в test-final; если РО уже в тесте, он добавляется в задание семинара модуля."""
    doc = _doc()
    doc.kit.assessments = [Assessment(id='test-final', kind='test', title='Итоговый тест')]
    cover_outcomes(doc)
    assert {q.assessment_id for q in doc.kit.questions} == {'test-final'}
    assert all(q.id.startswith('qf.') for q in doc.kit.questions)

    doc2 = _doc()
    doc2.kit.questions = [Question_(id='q1.1', assessment_id='test-m1', module_id='m1', stem='?', options=list('abcd'), key=0, lo_ids=['lo1'])]
    doc2.kit.tasks = [Task(id='s1', assessment_id='sem-m1', module_id='m1', title='Семинар', statement='s')]
    log = cover_outcomes(doc2)
    assert 'lo1' in doc2.kit.tasks[0].lo_ids
    assert 'РО 1: добавлен в задание «Семинар»' in log


def test_cover_outcomes_replaces_spare_when_volume_fixed() -> None:
    """SPEC-REPAIR-10: если объём теста задан в запросе, новый вопрос заменяет «лишний» вопрос по РО, проверяемому несколькими вопросами."""
    doc = _doc()
    doc.params.materials.test_questions = 3
    doc.kit.questions = [
        Question_(id=f'q1.{i}', assessment_id='test-m1', module_id='m1', stem='?', options=list('abcd'), key=0, lo_ids=['lo1'])
        for i in range(1, 4)
    ]
    doc.kit.tasks = [Task(id='s', assessment_id='sem-m1', module_id='m1', title='С', statement='s', lo_ids=['lo1', 'lo2'])]
    spare = _spare_question(doc, 'test-m1', 'm1')
    assert spare is not None and spare.lo_ids == ['lo1']
    n_before = sum(q.assessment_id == 'test-m1' for q in doc.kit.questions)
    cover_outcomes(doc)
    assert sum(q.assessment_id == 'test-m1' for q in doc.kit.questions) == n_before
    assert any(q.lo_ids == ['lo2'] for q in doc.kit.questions)
    assert _spare_question(_doc(), 'test-m1', 'm1') is None


def test_v09_lecture_titles_and_slides() -> None:
    """SPEC-REPAIR-11: V-09 — тема лекции приводится к теме УТП, у модулей без слайдов слайды собираются по плану и описанию темы."""
    doc = _doc()
    doc.kit.lectures = [Lecture(id='lec1.1', topic_id='t1.1', module_id='m1', title='что-то другое',
                                plan=[{'min': 10, 'text': 'Вступление'}, {'min': 80, 'text': 'Разбор'}])]
    log = repair(doc, _fail('V-09'))
    lec = doc.kit.lectures[0]
    assert lec.title == 'Циклы'
    assert [s.n for s in lec.slides] == [1, 2, 3]
    assert lec.slides[0].bullets == ['Цикл for перебирает элементы.', 'Цикл while работает по условию.']
    assert 'Лекция lec1.1: тема приведена к УТП' in log
    assert any(x.startswith('Модуль 1: слайды собраны') for x in log)


def test_v09_respects_requested_modules_with_slides() -> None:
    """SPEC-REPAIR-12: V-09 — модуль из запроса, у которого слайды уже есть, не пересобирается."""
    doc = _doc()
    doc.params.materials.slides_modules = [1]
    slides = [Slide(id='s', n=1, title='Свой', bullets=['x'])]
    doc.kit.lectures = [Lecture(id='lec1.1', topic_id='t1.1', module_id='m1', title='Циклы', slides=slides)]
    assert repair(doc, _fail('V-09')) == []
    assert doc.kit.lectures[0].slides == slides


def test_v17_reference_overlap_removed() -> None:
    """SPEC-REPAIR-13: V-17 — предложения, совпадающие с референсом по 8-граммам, удаляются из аннотаций, текстов модулей и описаний тем."""
    copied = 'Один два три четыре пять шесть семь восемь девять десять.'
    doc = _doc()
    doc.references = [ReferenceInfo(name='ref', text_sample='Начало. ' + copied + ' Конец.')]
    doc.modules[0].topics[0].description = f'Своё описание темы. {copied}'
    doc.kit.module_programs = [ModuleProgram(module_id='m1', annotation=f'{copied} Своя аннотация.', content=[{'topic_id': 't1.1', 'text': copied}])]
    log = repair(doc, _fail('V-17'))
    assert doc.modules[0].topics[0].description == 'Своё описание темы.'
    assert doc.kit.module_programs[0].annotation == 'Своя аннотация.'
    assert doc.kit.module_programs[0].content[0]['text'] == ''
    assert log == ['Убрано 3 предложений, совпавших с референсом']


def test_v17_without_reference_noop() -> None:
    """SPEC-REPAIR-14: V-17 — без текста референса ничего не удаляется и журнал пуст."""
    doc = _doc()
    assert repair(doc, _fail('V-17')) == []


def test_v08_v11_sections_rebuilt() -> None:
    """SPEC-REPAIR-15: V-08/V-11 — разделы шаблона пересобираются из графа программы."""
    doc = _doc()
    log = repair(doc, _fail('V-11'))
    assert doc.kit.sections and any('Разделы шаблона пересобраны' in x for x in log)


def test_v16_unconfirmed_sources_marked_once() -> None:
    """SPEC-REPAIR-16: V-16 — неподтверждённый источник помечается «[не подтверждено]» один раз, подтверждённый не меняется."""
    doc = _doc()
    doc.sources = [Source(id='s1', kind='book', bibl='Книга'), Source(id='s2', kind='book', bibl='Док', confirmed=True)]
    log = repair(doc, _fail('V-16'))
    assert doc.sources[0].bibl == 'Книга [не подтверждено]' and doc.sources[1].bibl == 'Док'
    assert log == ['Источник s1 помечен «не подтверждено»']
    assert repair(doc, _fail('V-16')) == []
