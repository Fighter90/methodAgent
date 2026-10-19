"""Спецификация specs/skill-review-assist.md: предложение правки по замечанию эксперта (FR-41, FR-47, FR-48)."""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import Criterion, Lecture, ProgramDoc, Question_, Slide, Task  # noqa: E402
from app.skills.review_assist import run as ra  # noqa: E402


class FakeLLM:
    def __init__(self, enabled: bool = True, exc: Exception | None = None) -> None:
        self.enabled, self.exc, self.calls = enabled, exc, []

    async def complete_json(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return ra.Proposal(proposal='Переформулировать критерий', new_text='Новый текст')


def _doc() -> ProgramDoc:
    doc = ProgramDoc(id='p', request='x')
    doc.kit.tasks = [Task(id='task1.1', assessment_id='sem-m1', module_id='m1', title='Задание 1', statement='Напишите цикл',
                          criteria=[Criterion(text='Работает', points=5), Criterion(text='Оформлено', points=5)])]
    doc.kit.questions = [Question_(id='q1.1', assessment_id='test-m1', stem='Что такое цикл?', options=['Повтор', 'Файл'], key=0)]
    doc.kit.lectures = [Lecture(id='lec1.1', topic_id='t', module_id='m1', title='Циклы',
                                plan=[{'min': 10, 'text': 'Введение'}, {'min': 80, 'text': 'Разбор'}],
                                slides=[Slide(id='sl1.1.1', n=1, title='Цикл for', bullets=['range', 'break'])])]
    return doc


@pytest.mark.parametrize('node,expected', [
    ('task1.1', 'Задание 1: Напишите цикл; критерии: Работает; Оформлено'),
    ('task1.1#c2', 'Критерий задания «Задание 1»: Оформлено'),
    ('task1.1#c9', 'Задание 1: Напишите цикл; критерии: Работает; Оформлено'),
    ('q1.1', 'Что такое цикл? | Повтор / Файл'),
    ('lec1.1', 'Лекция «Циклы»: Введение; Разбор'),
    ('lec1.1#p2', 'Пункт плана лекции «Циклы»: 80 мин — Разбор'),
    ('sl1.1.1', 'Слайд «Цикл for»: range; break'),
    ('nothing', ''),
])
def test_fragment_of(node: str, expected: str) -> None:
    """SPEC-REVIEW-01: fragment_of возвращает текст задания, критерия (#cN), вопроса, лекции, пункта плана (#pN) или слайда; неизвестный узел — пустая строка."""
    assert ra.fragment_of(_doc(), node) == expected


def test_fragment_of_zero_index_is_whole_element() -> None:
    """SPEC-REVIEW-02: IF номер критерия или пункта плана вне диапазона 1…N (в том числе 0), THEN возвращается текст элемента целиком."""
    doc = _doc()
    assert ra.fragment_of(doc, 'task1.1#c0') == ra.fragment_of(doc, 'task1.1')
    assert ra.fragment_of(doc, 'lec1.1#p0') == ra.fragment_of(doc, 'lec1.1')


async def test_propose_uses_model(monkeypatch) -> None:
    """SPEC-REVIEW-03: WHEN модель доступна и фрагмент найден, навык review_assist вызывается с фрагментом и замечанием и возвращает proposal."""
    llm = FakeLLM()
    monkeypatch.setattr(ra, 'get_llm', lambda: llm)
    text = await ra.propose(_doc(), 'm1', 'task1.1#c1', 'Уточнить критерий')
    assert text == 'Переформулировать критерий'
    kw = llm.calls[0]
    assert kw['skill'] == 'review_assist' and kw['schema'] is ra.Proposal
    assert json.loads(kw['user']) == {'fragment': 'Критерий задания «Задание 1»: Работает', 'comment': 'Уточнить критерий'}


@pytest.mark.parametrize('llm,node', [(FakeLLM(enabled=False), 'q1.1'), (FakeLLM(exc=ValueError('bad json')), 'q1.1'), (FakeLLM(), 'm1')])
async def test_propose_fallback(monkeypatch, llm: FakeLLM, node: str) -> None:
    """SPEC-REVIEW-04: IF модель недоступна, ответила ошибкой или фрагмент не найден, THEN возвращается шаблон с текстом замечания; часы и РО не меняются."""
    monkeypatch.setattr(ra, 'get_llm', lambda: llm)
    text = await ra.propose(_doc(), 'm1', node, 'Добавить пример')
    assert text.startswith('Учесть замечание эксперта: «Добавить пример».') and 'часы и РО не меняются' in text
    if node == 'm1':
        assert llm.calls == []


async def test_propose_full_affected(monkeypatch) -> None:
    """SPEC-REVIEW-05: propose_full возвращает предложение и список затрагиваемых элементов по графу связей (rebuild)."""
    from app.agent import workflow

    monkeypatch.setattr(ra, 'get_llm', lambda: FakeLLM(enabled=False))
    got = await ra.propose_full(_doc(), 'm1', 'q1.1', 'Исправить')
    assert got.affected == ['Вопрос q1.1'] and got.proposal.startswith('Учесть замечание')

    def boom(doc, base):
        raise LookupError(base)

    monkeypatch.setattr(workflow, 'descendants', boom)
    assert (await ra.propose_full(_doc(), 'm1', 'unknown', 'x')).affected == []
    assert (await ra.propose_full(_doc(), 'm1', '', 'x')).affected == []
