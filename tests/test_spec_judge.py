"""Спецификация specs/validation-judge.md: судья по смысловым правилам (FR-33)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import (  # noqa: E402
    Module,
    ModuleProgram,
    ProgramDoc,
    Report,
    RuleResult,
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


@pytest.mark.parametrize('llm_on,judge_on', [(False, True), (True, False)])
async def test_judge_skipped_when_disabled(monkeypatch, llm_on: bool, judge_on: bool) -> None:
    """SPEC-JUDGE-01: IF модель выключена или судья отключён настройкой, THEN судья не вызывается и журнал пуст."""
    llm = _setup(monkeypatch, FakeLLM(enabled=llm_on), judge_on)
    assert await j.judge(_doc()) == []
    assert llm.calls == []


async def test_judge_call_parameters(monkeypatch) -> None:
    """SPEC-JUDGE-02: судья вызывается с ролью judge, температурой 0, лимитом 4096 токенов, схемой JudgeOut и четырьмя правилами."""
    llm = _setup(monkeypatch, FakeLLM(out=j.JudgeOut()))
    await j.judge(_doc())
    kw = llm.calls[0]
    assert kw['role'] == 'judge' and kw['skill'] == 'judge' and kw['temperature'] == 0.0 and kw['max_tokens'] == 4096
    assert kw['schema'] is j.JudgeOut
    payload = json.loads(kw['user'])
    assert set(payload['rules']) == {'V-21', 'V-22', 'V-26', 'V-27'}


def test_view_is_compact() -> None:
    """SPEC-JUDGE-03: во вход судьи попадают только нужные поля: аннотации до 200 символов, последние 3 заметки агента до 160 символов."""
    v = j._view(_doc())
    assert v['title'] == 'Python' and v['modules'][0]['topics'] == ['1.1 Циклы']
    assert len(v['sample_text'][0]) == 200
    assert v['agent_notes'][0] == 'n2' and len(v['agent_notes'][-1]) == 160
    assert 'kit' not in v and 'request' not in v


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


async def test_judge_failure_keeps_code_results(monkeypatch) -> None:
    """SPEC-JUDGE-05: IF вызов судьи завершился ошибкой, THEN возвращается пустой журнал без исключения."""
    from app.llm.client import CallStats, LLMUnavailable

    _setup(monkeypatch, FakeLLM(exc=LLMUnavailable('judge: модель не ответила (TimeoutError)')))
    st = CallStats()
    assert await j.judge(_doc(), st) == []
    assert st.fallbacks[0]['skill'] == 'judge' and st.fallbacks[0]['fallback'] == 'оценки правил кодом без судьи'


def test_merge_adds_judge_messages() -> None:
    """SPEC-JUDGE-06: merge переводит pass в warn, не смягчает fail, добавляет замечания с префиксом «Судья:» и не трогает другие правила."""
    doc = _doc()
    doc.kit.judge = {'V-21': ['m1'], 'V-22': ['m2']}
    rep = Report(stage='kit', rules=[
        RuleResult(id='V-21', title='', check=None, kind='llm', status='pass'),
        RuleResult(id='V-22', title='', check=None, kind='llm', status='fail', messages=['код']),
        RuleResult(id='V-26', title='', check=None, kind='llm', status='pass'),
    ])
    j.merge(doc, rep)
    r21, r22, r26 = rep.rules
    assert r21.status == 'warn' and r21.messages == ['Судья: m1']
    assert r22.status == 'fail' and r22.messages == ['код', 'Судья: m2']
    assert r26.status == 'pass' and r26.messages == []
