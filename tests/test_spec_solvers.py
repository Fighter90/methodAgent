"""Спецификация specs/solvers.md: солвер часов и календаря (FR-15 – FR-18, NFR-05, NFR-09)."""

from __future__ import annotations

import dataclasses
import math
import os
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import Hours, Module, Params, ProgramDoc, ProgramType, Topic  # noqa: E402
from app.solver.calendar import apply_option, plan_calendar  # noqa: E402
from app.solver.hours import ModuleIn, TopicIn, largest_remainder, round_half_up, solve  # noqa: E402


def _modules(n: int = 3) -> list[ModuleIn]:
    return [ModuleIn(title=f'М{i}', weight=1.0 + i, topics=[TopicIn(f'Т{i}.{j}') for j in range(3)]) for i in range(n)]


@given(total=st.integers(0, 300), weights=st.lists(st.floats(0.1, 10), min_size=1, max_size=10))
@settings(max_examples=100, deadline=None)
def test_largest_remainder_deterministic(total: int, weights: list[float]) -> None:
    """SPEC-SOLVER-02: одинаковый вход даёт одинаковый результат."""
    assert largest_remainder(total, weights) == largest_remainder(total, list(weights))


def test_largest_remainder_tie_break() -> None:
    """SPEC-SOLVER-02: при равных остатках единица достаётся большему весу, затем меньшему номеру."""
    # Квоты 0.5 и 1.5: остатки равны, лишний час получает больший вес
    assert largest_remainder(2, [1, 3]) == [0, 2]
    # Веса и остатки равны: час получает элемент с меньшим номером
    assert largest_remainder(1, [1, 1]) == [1, 0]
    assert largest_remainder(2, [1, 1, 1]) == [1, 1, 0]
    a = solve(volume=72, final_hours=4, modules=_modules())
    b = solve(volume=72, final_hours=4, modules=_modules())
    assert [m.hours.as_dict() for m in a.modules] == [m.hours.as_dict() for m in b.modules]
    assert [[r.as_dict() for _, r in m.topics] for m in a.modules] == [[r.as_dict() for _, r in m.topics] for m in b.modules]


def test_round_half_up_not_bankers() -> None:
    """SPEC-SOLVER-03: доли округляются арифметически floor(x + 0.5), а не банковским округлением."""
    assert [round_half_up(x) for x in (0.5, 1.5, 2.5, 3.5, 2.49)] == [1, 2, 3, 4, 2]
    assert round(2.5) == 2  # встроенное round() банковское — солвер его не использует
    # 10 ч × 0.25 = 2.5 → 3 ч лекций (банковское дало бы 2)
    res = solve(volume=12, final_hours=2, modules=[ModuleIn(title='М', weight=1, lk_share=0.25, srs_share=0.0)])
    assert res.modules[0].hours.lk == 3


def test_min_practice_reduces_lk_and_srs() -> None:
    """SPEC-SOLVER-08: минимум практики выполняется уменьшением долей ЛК и СРС, с заметкой методисту."""
    mods = [ModuleIn(title='М', weight=1, lk_share=0.5, srs_share=0.4)]
    base = solve(volume=40, final_hours=0, modules=mods)
    assert base.totals.pr < 20
    res = solve(volume=40, final_hours=0, modules=mods, min_practice_hours=20)
    assert res.totals.pr >= 20
    assert res.totals.lk < base.totals.lk and res.totals.srs < base.totals.srs
    assert any('практика была не меньше 20 ч' in n for n in res.notes)


def test_min_practice_unreachable_note() -> None:
    """SPEC-SOLVER-08: если минимум практики не набирается, солвер оставляет заметку методисту."""
    mods = [ModuleIn(title='М', weight=1, lk_share=0.3, srs_share=0.2, lb_hours=8)]
    res = solve(volume=10, final_hours=0, modules=mods, min_practice_hours=50)
    assert res.totals.total == 10
    assert any('Не удалось набрать требуемый минимум практики' in n for n in res.notes)


def test_solver_takes_only_weights_and_shares() -> None:
    """SPEC-SOLVER-09: от каркаса солвер получает только веса, доли ЛК/СРС и часы ЛБ; часы модели игнорируются."""
    assert {f.name for f in dataclasses.fields(ModuleIn)} == {'title', 'weight', 'lk_share', 'srs_share', 'lb_hours', 'topics'}
    assert {f.name for f in dataclasses.fields(TopicIn)} == {'title', 'weight'}
    from app.agent.workflow import apply_solver

    doc = ProgramDoc(id='p', request='x', type=ProgramType.DPP_PK, params=Params(volume_h=36, final_assessment_hours=2))
    modules = [
        Module(id='m1', n=1, title='А', weight=1, hours=Hours(total=999, lk=999),
               topics=[Topic(id='t1.1', n='1.1', title='а', hours=Hours(total=500, pr=500))]),
        Module(id='m2', n=2, title='Б', weight=1, topics=[Topic(id='t2.1', n='2.1', title='б')]),
    ]
    apply_solver(doc, modules)
    assert doc.totals().total + doc.final_assessment.hours == 36
    assert doc.modules[0].hours.total == 17 and doc.modules[0].topics[0].hours.total == 17


def test_calendar_by_sessions() -> None:
    """SPEC-SOLVER-10: занятия «по H ч N раз в неделю» — ceil(объём / H) занятий и ceil(занятий / N) недель."""
    cal = plan_calendar(volume=25, requested_weeks=None, hours_per_day=None, days_per_week=None, sessions_per_week=2, session_hours=2)
    assert cal.sessions == math.ceil(25 / 2) == 13
    assert cal.weeks == math.ceil(13 / 2) == 7
    assert cal.hours_per_week == 4 and cal.session_hours == 2


@pytest.mark.parametrize(
    ('volume', 'weeks', 'hpd', 'dpw', 'exp_hpd', 'exp_days'),
    [
        (72, None, 4, None, 4, 18),  # нагрузка из запроса
        (40, 2, None, 5, 4, 10),  # по сроку: ceil(40 / (2·5)) = 4 ч
        (30, None, None, None, 6, 5),  # без срока и нагрузки — 6 ч
    ],
)
def test_calendar_by_days(volume: int, weeks: float | None, hpd: int | None, dpw: int | None, exp_hpd: int, exp_days: int) -> None:
    """SPEC-SOLVER-11: нагрузка в день — из запроса, иначе по сроку или 6 ч; рабочих дней ceil(объём / нагрузка)."""
    cal = plan_calendar(volume=volume, requested_weeks=weeks, hours_per_day=hpd, days_per_week=dpw)
    assert cal.hours_per_day == exp_hpd
    assert cal.work_days == exp_days == math.ceil(volume / exp_hpd)
    assert cal.weeks == math.ceil(exp_days / cal.days_per_week)


def test_calendar_conflict_and_options() -> None:
    """SPEC-SOLVER-12: плановых недель больше ceil(срок + 0.25) — конфликт с объяснением и варианты extend, six_days, raise_load."""
    ok = plan_calendar(volume=72, requested_weeks=4, hours_per_day=4, days_per_week=5)  # 18 дней = 4 недели
    assert ok.conflict == '' and ok.options == []
    cal = plan_calendar(volume=72, requested_weeks=2, hours_per_day=4, days_per_week=5)
    assert cal.weeks == 4 > math.ceil(2 + 0.25)
    assert '72 ч' in cal.conflict and '18 рабочих дней' in cal.conflict
    assert [o.id for o in cal.options] == ['extend', 'six_days', 'raise_load']
    extend, six, raise_ = cal.options
    assert extend.weeks == 4 and six.days_per_week == 6 and raise_.hours_per_day == math.ceil(72 / 10)


def test_calendar_apply_option_recomputes() -> None:
    """SPEC-SOLVER-13: выбор варианта пересчитывает рабочие дни, недели, недельную нагрузку и расписание."""
    items = [('Тема 1', 36, {'lk': 10, 'pr': 26}), ('Тема 2', 36, {'pr': 36})]
    cal = plan_calendar(volume=72, requested_weeks=2, hours_per_day=4, days_per_week=5, items=items)
    cal = apply_option(cal, 'raise_load', 72, items)
    assert cal.hours_per_day == 8 and cal.work_days == 9 and cal.weeks == 2 and cal.hours_per_week == 40
    assert len(cal.schedule) == 2 and sum(w['hours'] for w in cal.schedule) == 72
    cal = plan_calendar(volume=72, requested_weeks=2, hours_per_day=4, days_per_week=5, items=items)
    cal = apply_option(cal, 'six_days', 72, items)
    assert cal.days_per_week == 6 and cal.work_days == 18 and cal.weeks == 3 and cal.hours_per_week == 24
    assert [w['hours'] for w in cal.schedule] == [24, 24, 24]
    # Неизвестный вариант ничего не меняет
    assert apply_option(cal, 'nope', 72, items) is cal and cal.weeks == 3


def test_recompute_is_fast_and_offline(monkeypatch) -> None:
    """SPEC-SOLVER-15: пересчёт после правки часов методистом идёт за доли секунды без вызова модели."""
    from app.agent import workflow

    def no_llm(*_a, **_k):
        raise AssertionError('модель не должна вызываться')

    monkeypatch.setattr(workflow, 'get_llm', no_llm)
    doc = ProgramDoc(id='p', request='x', type=ProgramType.DPP_PK, params=Params(volume_h=144, final_assessment_hours=4))
    mods = [Module(id=f'm{i}', n=i, title=f'М{i}', weight=1,
                   topics=[Topic(id=f't{i}.{j}', n=f'{i}.{j}', title=f'т{i}{j}') for j in range(1, 6)]) for i in range(1, 9)]
    workflow.apply_solver(doc, mods)
    workflow.plan_doc_calendar(doc)
    doc.modules[0].hours.pr += 3
    started = time.perf_counter()
    workflow.recompute(doc)
    assert time.perf_counter() - started < 0.5
    m = doc.modules[0]
    assert m.hours.total == m.hours.kinds_sum() and sum(t.hours.total for t in m.topics) == m.hours.total


def test_calendar_conflict_strict_capacity() -> None:
    """SPEC-SOLVER-16"""
    # Контрпример аудита F08: 72 ч / 3 недели / 4 ч в день / 5 дней в неделю —
    # нужно 18 дней, доступно 15. Раньше допуск ceil(3 + 0.25) скрывал конфликт.
    cal = plan_calendar(volume=72, requested_weeks=3, hours_per_day=4, days_per_week=5)
    assert cal.conflict, 'невыполнимый срок должен давать конфликт'
    assert {o.id for o in cal.options} == {'extend', 'six_days', 'raise_load'}
    # Точный срок 4 недели при той же нагрузке выполним (18 дней ≤ 20) — конфликта нет.
    ok = plan_calendar(volume=72, requested_weeks=4, hours_per_day=4, days_per_week=5)
    assert not ok.conflict
    # Режим занятий: 36 занятий по 2 ч при 2 занятиях в неделю в срок 3 недели — конфликт.
    ses = plan_calendar(volume=72, requested_weeks=3, hours_per_day=None, days_per_week=None, sessions_per_week=2, session_hours=2)
    assert ses.conflict
