"""Спецификация specs/validation-judge.md: судья по смысловым правилам (FR-33, MET-33)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import (  # noqa: E402
    Criterion,
    Lecture,
    Module,
    ModuleProgram,
    ProgramDoc,
    Question_,
    Report,
    RuleResult,
    Slide,
    Task,
    Topic,
)
from app.validation import judge as j  # noqa: E402


class FakeLLM:
    def __init__(self, enabled: bool = True, out=None, exc: Exception | None = None) -> None:
        self.enabled, self.out, self.exc, self.calls = enabled, out, exc, []

    async def complete_json(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.out


def _setup(monkeypatch, llm: FakeLLM, judge_enabled: bool = True) -> FakeLLM:
    monkeypatch.setattr(j, 'get_llm', lambda: llm)
    monkeypatch.setattr(j, 'get_settings', lambda: SimpleNamespace(llm_judge_enabled=judge_enabled))
    return llm


def _doc() -> ProgramDoc:
    doc = ProgramDoc(id='p', request='x', title='Python', volume_h=16, goal='Цель')
    doc.modules = [Module(id='m1', n=1, title='Основы', topics=[Topic(id='t', n='1.1', title='Циклы')])]
    doc.kit.module_programs = [ModuleProgram(module_id='m1', annotation='А' * 500)]
    doc.agent_notes = ['n1', 'n2', 'n3', 'Б' * 300]
    return doc


def _kit_doc() -> ProgramDoc:
    """Каркас с материалами модуля: вопросы, задание, лекция со слайдами и планом."""
    doc = _doc()
    doc.kit.questions = [
        Question_(id='q1.1', assessment_id='test-m1', module_id='m1', stem='Какой цикл перебирает список?', options=['for', 'print'], key=0),
        Question_(id='q1.2', assessment_id='test-m1', module_id='m1', stem='Что делает print?', options=['печатает', 'цикл'], key=1),
    ]
    doc.kit.tasks = [Task(id='task1.1', assessment_id='sem-m1', module_id='m1', title='Задание',
                          statement='Напишите функцию сортировки', expected_result='Код и отчёт',
                          criteria=[Criterion(text='Решение корректно', points=4)])]
    doc.kit.lectures = [Lecture(id='lec1.1', topic_id='t', module_id='m1', title='Циклы',
                                plan=[{'min': 10, 'text': 'Актуализация'}, {'min': 40, 'text': 'Разбор примеров'}],
                                slides=[Slide(id='sl1.1.1', n=1, title='Цикл for', bullets=['перебор элементов', 'range()'])])]
    return doc


@pytest.mark.parametrize('llm_on,judge_on', [(False, True), (True, False)])
async def test_judge_skipped_when_disabled(monkeypatch, llm_on: bool, judge_on: bool) -> None:
    """SPEC-JUDGE-01: IF модель выключена или судья отключён настройкой, THEN судья не вызывается и журнал пуст."""
    llm = _setup(monkeypatch, FakeLLM(enabled=llm_on), judge_on)
    assert await j.judge(_doc()) == []
    assert llm.calls == []


async def test_judge_call_parameters(monkeypatch) -> None:
    """SPEC-JUDGE-02: судья вызывается с ролью judge, температурой 0, лимитом 4096 токенов, схемой JudgeOut и пятью правилами."""
    llm = _setup(monkeypatch, FakeLLM(out=j.JudgeOut()))
    await j.judge(_doc())
    kw = llm.calls[0]
    assert kw['role'] == 'judge' and kw['skill'] == 'judge' and kw['temperature'] == 0.0 and kw['max_tokens'] == 4096
    assert kw['schema'] is j.JudgeOut
    payload = json.loads(kw['user'])
    assert set(payload['rules']) == {'V-19', 'V-21', 'V-22', 'V-26', 'V-27'}


def test_view_is_compact() -> None:
    """SPEC-JUDGE-03: во вход судьи попадают только нужные поля: аннотации до 200 символов, последние 3 заметки агента до 160 символов."""
    v = j._view(_doc())
    assert v['title'] == 'Python' and v['modules'][0]['topics'] == ['1.1 Циклы']
    assert len(v['sample_text'][0]) == 200
    assert v['agent_notes'][0] == 'n2' and len(v['agent_notes'][-1]) == 160
    assert 'kit' not in v and 'request' not in v


def test_view_contains_real_materials() -> None:
    """SPEC-JUDGE-07: во входе судьи — реальные формулировки вопросов с вариантами и отмеченным ключом,
    задание с критериями и баллами, заголовки и пункты слайдов, строки плана лекции."""
    mat = j._view(_kit_doc())['modules'][0]['материалы']
    assert any('q1.1' in x and 'Какой цикл перебирает список?' in x and '✓ for' in x and '2) print' in x for x in mat['вопросы'])
    assert any('q1.2' in x and '✓ цикл' in x for x in mat['вопросы'])  # ключ виден судье
    assert any('task1.1' in x and 'Напишите функцию сортировки' in x and 'Решение корректно (4 б.)' in x for x in mat['задания'])
    assert any('sl1.1.1' in x and 'Цикл for' in x and 'перебор элементов' in x for x in mat['слайды'])
    assert any('10 мин — Актуализация' in x for x in mat['планы'])


async def test_judge_receives_materials(monkeypatch) -> None:
    """SPEC-JUDGE-07: судья получает сам материал вопроса с ключом — подмена ключа становится видимой."""
    llm = _setup(monkeypatch, FakeLLM(out=j.JudgeOut()))
    await j.judge(_kit_doc())
    payload = json.loads(llm.calls[0]['user'])
    mat = payload['program']['modules'][0]['материалы']
    assert any('q1.2' in x and '✓ цикл' in x for x in mat['вопросы'])


def test_view_truncates_materials() -> None:
    """SPEC-JUDGE-07: больше 12 вопросов на модуль — 12 строк и пометка «усечено»; длинные тексты обрезаются с «…»."""
    doc = _doc()
    for i in range(1, 16):
        doc.kit.questions.append(Question_(id=f'q1.{i}', assessment_id='t', module_id='m1',
                                           stem=f'Вопрос номер {i} про программирование? ' + 'длинный текст ' * 20,
                                           options=['а', 'б'], key=0))
    mat = j._view(doc)['modules'][0]['материалы']
    assert len(mat['вопросы']) == j._MAX_QUESTIONS and mat['усечено'] == 'да'
    assert all(len(x) <= j._ITEM_CHARS + 40 for x in mat['вопросы'])  # 200 — формулировка, остальное — id и варианты
    assert any('…' in x for x in mat['вопросы'])  # длинная формулировка усечена


def test_view_module_budget() -> None:
    """SPEC-JUDGE-07: материалы одного модуля укладываются в бюджет символов, излишек усекается с пометкой."""
    doc = _doc()
    for i in range(1, 40):
        doc.kit.questions.append(Question_(id=f'q1.{i}', assessment_id='t', module_id='m1',
                                           stem=f'В{i} ' + 'х' * 180, options=['а' * 50, 'б'], key=0))
        doc.kit.tasks.append(Task(id=f'task1.{i}', assessment_id='s', module_id='m1', title='Т',
                                  statement='с ' * 100, criteria=[Criterion(text='к', points=1)]))
    mat = j._view(doc)['modules'][0]['материалы']
    total = sum(len(x) for values in mat.values() if isinstance(values, list) for x in values)
    assert total <= j._MODULE_CHARS and mat['усечено'] == 'да'


async def test_only_warn_with_messages_kept(monkeypatch) -> None:
    """SPEC-JUDGE-04: в комплект сохраняются только warn известных правил с непустыми замечаниями (до 3, без пробелов по краям)."""
    out = j.JudgeOut(verdicts=[
        j.Verdict(rule='V-21', status='warn', messages=[' Тема 2.1 раньше 1.1 ', '', 'b', 'c', 'd']),
        j.Verdict(rule='V-22', status='pass', messages=['игнор']),
        j.Verdict(rule='V-26', status='warn', messages=['  ']),
        j.Verdict(rule='V-99', status='warn', messages=['чужое']),
    ])
    _setup(monkeypatch, FakeLLM(out=out))
    doc = _doc()
    doc.kit.judge = {'V-27': ['старое']}
    log = await j.judge(doc)
    assert doc.kit.judge == {'V-21': ['Тема 2.1 раньше 1.1', 'b']}
    assert log == ['V-21: Тема 2.1 раньше 1.1']


async def test_verdict_node_tagged(monkeypatch) -> None:
    """SPEC-JUDGE-04: узел из вердикта попадает в замечание пометкой [узел] и в журнал."""
    out = j.JudgeOut(verdicts=[j.Verdict(rule='V-19', status='warn', node='q1.2', messages=['Ключ указывает не на тот вариант'])])
    _setup(monkeypatch, FakeLLM(out=out))
    doc = _doc()
    log = await j.judge(doc)
    assert doc.kit.judge == {'V-19': ['[q1.2] Ключ указывает не на тот вариант']}
    assert log == ['V-19: [q1.2] Ключ указывает не на тот вариант']


async def test_judge_failure_keeps_code_results(monkeypatch) -> None:
    """SPEC-JUDGE-05: IF вызов судьи завершился ошибкой, THEN возвращается пустой журнал без исключения."""
    from app.llm.client import CallStats, LLMUnavailable

    _setup(monkeypatch, FakeLLM(exc=LLMUnavailable('judge: модель не ответила (TimeoutError)')))
    st = CallStats()
    assert await j.judge(_doc(), st) == []
    assert st.fallbacks[0]['skill'] == 'judge' and st.fallbacks[0]['fallback'] == 'оценки правил кодом без судьи'


def test_merge_adds_judge_messages() -> None:
    """SPEC-JUDGE-06: merge переводит pass в warn, не смягчает fail, добавляет замечания с префиксом «Судья:»,
    переносит узел из пометки [узел] в nodes и не трогает другие правила."""
    doc = _doc()
    doc.kit.judge = {'V-21': ['m1'], 'V-22': ['[lo2] не проверяемо']}
    rep = Report(stage='kit', rules=[
        RuleResult(id='V-21', title='', check=None, kind='llm', status='pass', nodes=['t1']),
        RuleResult(id='V-22', title='', check=None, kind='llm', status='fail', messages=['код']),
        RuleResult(id='V-26', title='', check=None, kind='llm', status='pass'),
    ])
    j.merge(doc, rep)
    r21, r22, r26 = rep.rules
    assert r21.status == 'warn' and r21.messages == ['Судья: m1'] and r21.nodes == ['t1']
    assert r22.status == 'fail' and r22.messages == ['код', 'Судья: [lo2] не проверяемо'] and r22.nodes == ['lo2']
    assert r26.status == 'pass' and r26.messages == []


def test_judge_rows_separate_from_code() -> None:
    """SPEC-JUDGE-08: замечания судьи — отдельные строки отчёта с узлами; сообщения кода их не содержат,
    неизвестные правила отбрасываются, в действиях — строки «Судья (…): …», кодовых правил по-прежнему 27."""
    from app.validation.report import build_report

    doc = _kit_doc()
    doc.kit.judge = {'V-26': ['[q1.2] Вопрос не на русском'], 'V-99': ['чужое']}
    rep = build_report(doc, 'kit')
    res = {r.id: r for r in rep.rules}
    row = res['V-26-judge']
    assert row.check is None and row.kind == 'llm' and row.status == 'warn'
    assert row.messages == ['[q1.2] Вопрос не на русском'] and row.nodes == ['q1.2']
    assert 'Судья:' not in ' '.join(res['V-26'].messages)
    assert not any(rid.startswith('V-99') for rid in res)
    assert any(a.startswith('Судья (V-26):') for a in rep.actions)
    assert len([r for r in rep.rules if not r.id.endswith('-judge')]) == 27


async def test_audit_counterexample_is_caught(monkeypatch) -> None:
    """SPEC-JUDGE-08, находка аудита F11: подменённый ключ ловит судья по материалам (узел вопроса),
    английский текст вопроса и слайда ловит V-26 кодом без модели, пустой критерий — V-18, дубль вопроса
    с другим ключом — V-25; сообщения судьи не смешиваются с кодом."""
    from app.validation.report import build_report

    doc = _kit_doc()
    doc.kit.questions += [
        Question_(id='q1.3', assessment_id='test-m1', module_id='m1', stem='Какой цикл перебирает список?',
                  options=['цикл for', 'оператор print'], key=1),  # структурно корректный ключ, по смыслу неверный
        Question_(id='q1.4', assessment_id='test-m1', module_id='m1', stem='What does the len function return?',
                  options=['length', 'type'], key=0),
    ]
    doc.kit.tasks.append(Task(id='task1.2', assessment_id='sem-m1', module_id='m1', title='Без критериев',
                              statement='с', criteria=[Criterion(text='  ', points=3)]))
    doc.kit.lectures[0].slides.append(Slide(id='sl1.1.6', n=6, title='Summary', bullets=['Here is what we learned today']))
    out = j.JudgeOut(verdicts=[j.Verdict(rule='V-19', status='warn', node='q1.3',
                                         messages=['Ключ указывает на print, верный ответ — «цикл for»'])])
    _setup(monkeypatch, FakeLLM(out=out))
    await j.judge(doc)
    rep = build_report(doc, 'kit')
    res = {r.id: r for r in rep.rules}
    assert res['V-19-judge'].status == 'warn' and res['V-19-judge'].nodes == ['q1.3']
    assert 'Судья:' not in ' '.join(res['V-19'].messages)
    assert 'q1.4' in res['V-26'].nodes and 'sl1.1.6' in res['V-26'].nodes
    assert res['V-18'].status == 'fail' and 'task1.2' in res['V-18'].nodes
    assert 'q1.3' in res['V-25'].nodes and any('разными ключами' in m for m in res['V-25'].messages)
