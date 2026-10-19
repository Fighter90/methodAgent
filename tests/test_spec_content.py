"""Спецификация specs/skill-content.md: содержание модуля по каркасу (FR-25…FR-29)."""

from __future__ import annotations

import json
import os

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import (  # noqa: E402
    Competency,
    Hours,
    Indicator,
    LearningOutcome,
    Module,
    ProgramDoc,
    ProgramType,
    Topic,
)
from app.skills.content import run as content  # noqa: E402
from app.skills.content.run import ModuleContentLLM  # noqa: E402


class FakeLLM:
    def __init__(self, data: dict | None = None, enabled: bool = True, exc: Exception | None = None) -> None:
        self.data, self.enabled, self.exc, self.calls = data, enabled, exc, []

    async def complete_json(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return ModuleContentLLM.model_validate(self.data)


def _doc(ptype: ProgramType = ProgramType.DPP_PK) -> ProgramDoc:
    los = [LearningOutcome(id=f'lo{i}', code=f'РО {i}', text=t) for i, t in
           enumerate(['Пишет циклы на Python', 'Пишет функции', 'Читает файлы pandas'], start=1)]
    return ProgramDoc(
        id='p', request='x', title='Python для аналитиков', type=ptype,
        competencies=[Competency(id='c1', code='ПК-1', title='К', indicators=[Indicator(id='i1', kind='can', text='x', outcomes=los)])],
        modules=[
            Module(id='m1', n=1, title='Основы Python', topics=[
                Topic(id='t1.1', n='1.1', title='Циклы', description='Цикл for, цикл while', hours=Hours(total=4, lk=2, pr=2), lo_ids=['lo1']),
                Topic(id='t1.2', n='1.2', title='Функции', description='Аргументы', hours=Hours(total=2, lk=2), lo_ids=['lo2']),
            ]),
            Module(id='m2', n=2, title='Файлы', topics=[Topic(id='t2.1', n='2.1', title='Файлы', hours=Hours(total=2, pr=2), lo_ids=['lo3'])]),
        ],
    )


async def _run(monkeypatch, llm: FakeLLM, doc: ProgramDoc | None = None, n: int = 5, slides: set[str] | None = None):
    doc = doc or _doc()
    monkeypatch.setattr(content, 'get_llm', lambda: llm)
    return await content.run(doc, doc.modules[0], n_questions=n, test_id='test-m1', slide_topics=slides or set())


async def test_fallback_when_model_disabled(monkeypatch) -> None:
    """SPEC-CONTENT-01: IF модель недоступна, THEN модуль собирается по шаблону: source=template, аннотация из РО, тексты тем из описаний."""
    llm = FakeLLM(enabled=False)
    mc = await _run(monkeypatch, llm)
    assert mc.source == 'template' and llm.calls == []
    assert mc.program.annotation.startswith('Модуль «Основы Python» формирует результаты обучения: Пишет циклы на Python; Пишет функции')
    assert [c['text'] for c in mc.program.content] == ['Цикл for, цикл while', 'Аргументы']
    assert mc.program.control_questions == ['Раскройте содержание темы «Циклы».', 'Раскройте содержание темы «Функции».']


async def test_fallback_questions(monkeypatch) -> None:
    """SPEC-CONTENT-02: шаблонный тест содержит ровно n вопросов: 4 разных варианта, верный ответ — РО темы, ключ чередуется i % 4, дистракторы — из других модулей."""
    mc = await _run(monkeypatch, FakeLLM(enabled=False), n=6)
    assert [q.id for q in mc.questions] == [f'q1.{i}' for i in range(1, 7)]
    for i, q in enumerate(mc.questions):
        assert len(q.options) == 4 == len(set(q.options))
        assert q.key == i % 4 and q.assessment_id == 'test-m1' and q.module_id == 'm1'
        lo_text = {'lo1': 'Пишет циклы на Python', 'lo2': 'Пишет функции'}[q.lo_ids[0]]
        assert q.options[q.key] == lo_text
    assert any('Читает файлы pandas' in q.options for q in mc.questions)


async def test_fallback_tasks_and_lectures(monkeypatch) -> None:
    """SPEC-CONTENT-03: шаблонные задания — по одному на тему с практикой, с критериями 4+4+2; лекции — только для тем со слайдами, 5 слайдов."""
    mc = await _run(monkeypatch, FakeLLM(enabled=False), slides={'t1.2'})
    assert [t.topic_id for t in mc.tasks] == ['t1.1']
    assert [c.points for c in mc.tasks[0].criteria] == [4, 4, 2] and mc.tasks[0].lo_ids == ['lo1']
    assert [lec.topic_id for lec in mc.lectures] == ['t1.2'] and len(mc.lectures[0].slides) == 5
    assert mc.lectures[0].duration_min == 90 and sum(p['min'] for p in mc.lectures[0].plan) == 90


async def test_fallback_internship_tasks_every_topic(monkeypatch) -> None:
    """SPEC-CONTENT-04: для стажировки шаблонное задание создаётся для каждой темы, в том числе без часов практики."""
    mc = await _run(monkeypatch, FakeLLM(enabled=False), doc=_doc(ProgramType.DPP_PK_INTERNSHIP))
    assert [t.topic_id for t in mc.tasks] == ['t1.1', 't1.2']
    assert mc.tasks[0].title.startswith('Задание стажировки')


async def test_fallback_on_model_error(monkeypatch) -> None:
    """SPEC-CONTENT-05: IF модель ответила ошибкой, THEN используется шаблонное содержание без исключения."""
    mc = await _run(monkeypatch, FakeLLM(exc=RuntimeError('LLM down')))
    assert mc.source == 'template' and len(mc.questions) == 5


LLM_DATA = {
    'annotation': '',
    'topics': [{'n': '1.1', 'content': 'Текст про циклы'}],
    'questions': [
        {'stem': ' Что делает for? ', 'options': [' перебирает ', 'удаляет', 'пишет файл'], 'key': 9, 'lo': ['РО1']},
        {'stem': 'Что вернёт функция без return?', 'options': ['None', '0', 'ошибку'], 'key': 0, 'lo': ['РО 7']},
    ],
    'tasks': [
        {'topic': '1.1', 'statement': 'Напишите цикл', 'criteria': [{'text': 'Работает', 'points': 0}], 'lo': ['РО 2']},
        {'statement': 'Без темы'},
    ],
    'lectures': [
        {'topic': '1.1', 'plan': [{'min': 20, 'text': 'Вступление'}, {'min': None, 'text': 'Разбор'}], 'code': 'print(1)',
         'slides': [{'title': f'С{i}', 'bullets': [str(b) for b in range(9)]} for i in range(10)]},
    ],
    'sources': ['a', 'b', 'c', 'd'],
    'interview': ['коротко', 'Какие инструменты вы использовали в работе?'] + [f'Вопрос собеседования номер {i} про практику' for i in range(8)],
}


async def test_llm_content_mapped(monkeypatch) -> None:
    """SPEC-CONTENT-06: ответ модели переводится в комплект: source=llm, ключ вне диапазона → 0, коды РО → id (иначе по кругу), недостающие вопросы добираются шаблоном."""
    mc = await _run(monkeypatch, FakeLLM(LLM_DATA), n=4)
    assert mc.source == 'llm'
    assert mc.program.annotation == 'Модуль «Основы Python».'
    assert [c['text'] for c in mc.program.content] == ['Текст про циклы', 'Аргументы']
    q1, q2, *rest = mc.questions
    assert q1.stem == 'Что делает for?' and q1.options[0] == 'перебирает' and q1.key == 0 and q1.lo_ids == ['lo1']
    assert q2.lo_ids == ['lo2']
    assert len(mc.questions) == 4 and [q.id for q in mc.questions] == ['q1.1', 'q1.2', 'q1.3', 'q1.4'] and len(rest) == 2


async def test_llm_tasks_criteria(monkeypatch) -> None:
    """SPEC-CONTENT-07: задания модели получают тему по номеру (иначе по кругу), баллы не меньше 1, критерии по умолчанию при их отсутствии."""
    mc = await _run(monkeypatch, FakeLLM(LLM_DATA))
    t1, t2 = mc.tasks
    assert t1.topic_id == 't1.1' and t1.title == 'Задание к теме 1.1' and t1.criteria[0].points == 1 and t1.lo_ids == ['lo2']
    assert t2.topic_id == 't1.2' and [c.points for c in t2.criteria] == [4, 4, 2] and t2.lo_ids == ['lo2']
    assert t1.assessment_id == 'sem-m1' and t1.id == 'task1.1'


async def test_llm_lectures_sources_interview(monkeypatch) -> None:
    """SPEC-CONTENT-08: лекции — только для тем со слайдами (до 8 слайдов по 6 тезисов, пример кода), тема без слайдов модели — шаблонная лекция; до 3 источников и до 6 вопросов собеседования длиннее 15 символов."""
    mc = await _run(monkeypatch, FakeLLM(LLM_DATA), slides={'t1.1', 't1.2'})
    lec1, lec2 = mc.lectures
    assert len(lec1.slides) == 8 and all(len(s.bullets) == 6 for s in lec1.slides)
    assert lec1.code_examples == ['print(1)'] and lec1.plan[0]['text'] == 'Вступление' and lec1.plan[1]['min'] == 10 and lec1.duration_min == 90
    assert len(lec2.slides) == 5
    assert mc.sources == ['a', 'b', 'c']
    assert len(mc.interview) == 6 and 'коротко' not in mc.interview


async def test_llm_without_tasks_uses_template_tasks(monkeypatch) -> None:
    """SPEC-CONTENT-09: IF модель не вернула заданий, THEN задания берутся из шаблона."""
    mc = await _run(monkeypatch, FakeLLM({'questions': []}))
    assert mc.source == 'llm' and [t.topic_id for t in mc.tasks] == ['t1.1'] and len(mc.questions) == 5


async def test_llm_request_payload(monkeypatch) -> None:
    """SPEC-CONTENT-10: в модель уходят темы с РО и признаком практики, число вопросов, версии только встречающихся инструментов; без слайдов лимит токенов ≤ 4500."""
    llm = FakeLLM({'questions': []})
    await _run(monkeypatch, llm, n=3)
    kw = llm.calls[0]
    payload = json.loads(kw['user'])
    assert kw['skill'] == 'content' and kw['max_tokens'] <= 4500
    assert payload['n_questions'] == 3 and payload['need_slides'] is False
    assert payload['topics'][0]['lo'] == ['РО 1'] and payload['topics'][0]['has_practice'] is True
    assert payload['topics'][1]['has_practice'] is False
    assert 'python' in payload['tool_versions_2026'] and 'kubernetes' not in payload['tool_versions_2026']
    llm2 = FakeLLM({'questions': []})
    await _run(monkeypatch, llm2, slides={'t1.1'})
    from app.skills.base import skill

    assert llm2.calls[0]['max_tokens'] == skill('content').max_tokens


async def test_blocked_services_removed_from_llm_content(monkeypatch) -> None:
    """SPEC-CONTENT-11: вопросы с сервисами, недоступными в России, отбрасываются и заменяются шаблонными; в остальном тексте сервис заменяется на «зарубежный сервис»."""
    data = {'annotation': 'Работаем с ChatGPT (OpenAI) и GigaChat',
            'questions': [{'stem': 'Где писать промпт?', 'options': ['ChatGPT', 'GigaChat', 'Блокнот'], 'key': 1}],
            'tasks': [{'statement': 'Сравните Midjourney и Кандинский'}]}
    mc = await _run(monkeypatch, FakeLLM(data), n=2)
    assert 'ChatGPT' not in mc.program.annotation and 'зарубежный сервис' in mc.program.annotation
    assert 'Midjourney' not in mc.tasks[0].statement
    assert all('ChatGPT' not in ' '.join(q.options) for q in mc.questions) and len(mc.questions) == 2


def test_scrub_without_blocklist(monkeypatch) -> None:
    """SPEC-CONTENT-12: IF список заблокированных сервисов пуст, THEN ответ модели не меняется."""
    monkeypatch.setattr(content, 'tools', lambda: {'current': {}})
    data = ModuleContentLLM.model_validate({'annotation': 'ChatGPT'})
    assert content.scrub_blocked(data) is data and data.annotation == 'ChatGPT'
