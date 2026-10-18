"""Календарный график: дни и недели по нагрузке, конфликты ограничений (ТЗ, 4.6, шаг 5)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class CalendarOptionOut:
    id: str
    title: str
    weeks: int
    hours_per_day: int
    days_per_week: int


@dataclass
class CalendarOut:
    weeks: int
    work_days: int
    hours_per_day: int
    days_per_week: int
    hours_per_week: int
    sessions: int
    session_hours: int
    requested_weeks: float | None
    conflict: str = ''
    options: list[CalendarOptionOut] = field(default_factory=list)
    schedule: list[dict] = field(default_factory=list)


def plan_calendar(
    *,
    volume: int,
    requested_weeks: float | None,
    hours_per_day: int | None,
    days_per_week: int | None,
    sessions_per_week: int | None = None,
    session_hours: int | None = None,
    items: Sequence[tuple[str, int]] = (),
) -> CalendarOut:
    """Строит график и при конфликте предлагает варианты, не нарушая ограничения молча.

    Если заданы занятия (N в неделю по H часов) — график строится по занятиям.
    Иначе: рабочих дней = ⌈часы / нагрузка в день⌉, недель = ⌈дни / дней в неделю⌉.
    """
    dpw = days_per_week or 5
    if sessions_per_week and session_hours:
        sessions = math.ceil(volume / session_hours)
        weeks = math.ceil(sessions / sessions_per_week)
        cal = CalendarOut(
            weeks=weeks,
            work_days=sessions,
            hours_per_day=session_hours,
            days_per_week=sessions_per_week,
            hours_per_week=sessions_per_week * session_hours,
            sessions=sessions,
            session_hours=session_hours,
            requested_weeks=requested_weeks,
        )
    else:
        hpd = hours_per_day or 0
        if not hpd:
            # Без ограничений: равномерно по запрошенному сроку, не больше 8 ч в день
            if requested_weeks:
                hpd = min(8, max(2, math.ceil(volume / (math.floor(requested_weeks) * dpw or dpw))))
            else:
                hpd = 6
        work_days = math.ceil(volume / hpd)
        weeks = math.ceil(work_days / dpw)
        cal = CalendarOut(
            weeks=weeks,
            work_days=work_days,
            hours_per_day=hpd,
            days_per_week=dpw,
            hours_per_week=min(volume, hpd * dpw),
            sessions=0,
            session_hours=0,
            requested_weeks=requested_weeks,
        )

    if requested_weeks and cal.weeks > math.ceil(requested_weeks + 0.25):
        hpd = cal.hours_per_day
        need_days = cal.work_days
        avail_days = math.floor(requested_weeks * cal.days_per_week)
        cal.conflict = (
            f'{volume} ч при нагрузке не больше {hpd} ч в день требуют не меньше {need_days} рабочих дней '
            f'(≈ {cal.weeks} нед. при {cal.days_per_week}-дневной неделе), а в сроке около '
            f'{requested_weeks:g} нед. — {avail_days} рабочих дней'
        )
        six = math.ceil(need_days / 6)
        hpd_needed = math.ceil(volume / max(avail_days, 1))
        cal.options = [
            CalendarOptionOut('extend', f'Увеличить срок до {cal.weeks} недель', cal.weeks, hpd, cal.days_per_week),
            CalendarOptionOut('six_days', f'Перейти на шестидневную неделю (≈ {six} недель)', six, hpd, 6),
            CalendarOptionOut(
                'raise_load',
                f'Согласовать с заказчиком нагрузку {hpd_needed} ч в день в исходном сроке',
                math.ceil(requested_weeks),
                hpd_needed,
                cal.days_per_week,
            ),
        ]
    cal.schedule = build_schedule(cal, items)
    return cal


def apply_option(cal: CalendarOut, option_id: str, volume: int, items: Sequence[tuple[str, int]] = ()) -> CalendarOut:
    """Применяет выбранный методистом вариант разрешения конфликта."""
    opt = next((o for o in cal.options if o.id == option_id), None)
    if opt is None:
        return cal
    cal.hours_per_day = opt.hours_per_day
    cal.days_per_week = opt.days_per_week
    cal.work_days = math.ceil(volume / opt.hours_per_day)
    cal.weeks = math.ceil(cal.work_days / opt.days_per_week)
    cal.hours_per_week = min(volume, opt.hours_per_day * opt.days_per_week)
    cal.schedule = build_schedule(cal, items)
    return cal


_KINDS = ('lk', 'pr', 'lb', 'srs', 'ia')


def _week(n: int) -> dict:
    return {'week': n, 'hours': 0, 'days': 0, 'items': [], **dict.fromkeys(_KINDS, 0)}


def build_schedule(cal: CalendarOut, items: Sequence[tuple]) -> list[dict]:
    """Раскладывает элементы (тема, часы[, часы по видам]) по неделям с учётом недельной нагрузки.

    Часы по видам работы (ЛК, ПР, ЛБ, СРС, ИА) идут в неделю в порядке занятий темы: сначала лекции, затем практика.
    """
    capacity = cal.hours_per_week or 1
    weeks: list[dict] = []
    current: dict = _week(1)
    for item in items:
        title, hours = item[0], item[1]
        kinds = dict(item[2]) if len(item) > 2 else {'srs': hours}
        left = hours
        while left > 0:
            free = capacity - current['hours']
            if free <= 0:
                weeks.append(current)
                current = _week(current['week'] + 1)
                free = capacity
            take = min(free, left)
            current['hours'] += take
            rest = take
            for k in _KINDS:
                part = min(rest, kinds.get(k, 0))
                current[k] += part
                kinds[k] = kinds.get(k, 0) - part
                rest -= part
            if title not in current['items']:
                current['items'].append(title)
            left -= take
    if current['hours']:
        weeks.append(current)
    for w in weeks:
        w['days'] = math.ceil(w['hours'] / max(cal.hours_per_day, 1))
    return weeks
