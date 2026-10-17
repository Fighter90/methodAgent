"""Детерминированный солвер часов hours_solver (ТЗ, подраздел 4.6).

Модель предлагает только структуру: веса модулей и тем, доли лекций и СРС.
Часы считает код методом наибольших остатков, поэтому суммы сходятся на всех
уровнях, а одинаковый вход всегда даёт одинаковый результат.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

KINDS: tuple[str, ...] = ('lk', 'pr', 'lb', 'srs')


def round_half_up(x: float) -> int:
    """Арифметическое округление (в Python round() банковское)."""
    return math.floor(x + 0.5)


def largest_remainder(total: int, weights: Sequence[float], *, minimum: int = 0) -> list[int]:
    """Делит целое `total` пропорционально весам методом наибольших остатков.

    При равных остатках час получает элемент с большим весом, затем с меньшим
    номером. `minimum` гарантирует каждому элементу не меньше заданного числа
    часов, если это возможно.
    """
    n = len(weights)
    if n == 0:
        return []
    if total <= 0:
        return [0] * n
    base = [minimum] * n if minimum * n <= total else [0] * n
    rest = total - sum(base)
    wsum = sum(max(w, 0.0) for w in weights)
    norm = [max(w, 0.0) / wsum for w in weights] if wsum > 0 else [1.0 / n] * n
    quotas = [rest * w for w in norm]
    floors = [math.floor(q + 1e-9) for q in quotas]
    remaining = rest - sum(floors)
    order = sorted(range(n), key=lambda i: (-(quotas[i] - floors[i]), -norm[i], i))
    for i in order[:remaining]:
        floors[i] += 1
    return [b + f for b, f in zip(base, floors, strict=True)]


@dataclass
class TopicIn:
    title: str
    weight: float = 1.0


@dataclass
class ModuleIn:
    title: str
    weight: float
    lk_share: float = 0.33
    srs_share: float = 0.2
    lb_hours: int = 0
    topics: list[TopicIn] = field(default_factory=list)


@dataclass
class HoursRow:
    total: int = 0
    lk: int = 0
    pr: int = 0
    lb: int = 0
    srs: int = 0

    def as_dict(self) -> dict[str, int]:
        return {'total': self.total, 'lk': self.lk, 'pr': self.pr, 'lb': self.lb, 'srs': self.srs}


@dataclass
class ModuleOut:
    title: str
    hours: HoursRow
    topics: list[tuple[str, HoursRow]]
    quota: float
    remainder: float


@dataclass
class SolverResult:
    modules: list[ModuleOut]
    totals: HoursRow
    final_hours: int
    volume: int
    notes: list[str] = field(default_factory=list)


def _split_kinds(hours: int, lk_share: float, srs_share: float, lb: int) -> HoursRow:
    """ЛК и СРС — по долям, ЛБ — задано, практика закрывает строку."""
    lk_s, srs_s = lk_share, srs_share
    lb = min(max(lb, 0), hours)
    for _ in range(50):
        lk = round_half_up(hours * lk_s)
        srs = round_half_up(hours * srs_s)
        pr = hours - lk - lb - srs
        if pr >= 0:
            return HoursRow(total=hours, lk=lk, pr=pr, lb=lb, srs=srs)
        lk_s *= 0.85
        srs_s *= 0.85
    return HoursRow(total=hours, lk=0, pr=hours - lb, lb=lb, srs=0)


def _split_topics(module_row: HoursRow, topics: Sequence[TopicIn]) -> list[HoursRow]:
    """Делит строку модуля по темам так, что суммы тем равны модулю по каждому виду.

    Сначала тема получает итог (не меньше 1 ч), затем виды работы раздаются
    последовательно пропорционально оставшимся часам каждого вида — это
    всегда допустимо и сохраняет обе суммы (по строкам и по столбцам).
    """
    totals = largest_remainder(module_row.total, [t.weight for t in topics], minimum=1)
    remaining = {k: getattr(module_row, k) for k in KINDS}
    rows: list[HoursRow] = []
    for idx, t_total in enumerate(totals):
        if idx == len(totals) - 1:
            row = HoursRow(total=t_total, **remaining)
        else:
            rem_h = sum(remaining.values())
            weights = [remaining[k] / rem_h if rem_h else 0 for k in KINDS]
            parts = largest_remainder(t_total, weights)
            # Квота вида не превышает остаток вида: ⌈t·r_k/R⌉ ≤ r_k при t ≤ R
            parts = [min(p, remaining[k]) for p, k in zip(parts, KINDS, strict=True)]
            deficit = t_total - sum(parts)
            for k_i, k in enumerate(KINDS):
                if deficit <= 0:
                    break
                free = remaining[k] - parts[k_i]
                add = min(free, deficit)
                parts[k_i] += add
                deficit -= add
            row = HoursRow(total=t_total, **dict(zip(KINDS, parts, strict=True)))
        for k in KINDS:
            remaining[k] -= getattr(row, k)
        rows.append(row)
    return rows


def solve(
    *,
    volume: int,
    final_hours: int,
    modules: Sequence[ModuleIn],
    internship: bool = False,
    min_practice_hours: int = 0,
) -> SolverResult:
    """Распределяет `volume` часов по модулям, видам работы и темам.

    Args:
        volume: запрошенный объём программы V.
        final_hours: часы итоговой аттестации A (входят в V).
        modules: структура от модели — веса и доли.
        internship: режим «стажировка» — все часы модулей идут в СРС.
        min_practice_hours: минимум ПР по программе (V-07); при нехватке
            солвер уменьшает доли лекций и СРС.
    """
    if volume <= 0:
        raise ValueError('Объём программы должен быть положительным')
    if not modules:
        raise ValueError('Нужен хотя бы один модуль')
    final_hours = max(0, min(final_hours, volume - 1))
    available = volume - final_hours
    notes: list[str] = []

    weights = [max(m.weight, 0.0) for m in modules]
    if sum(weights) <= 0:
        weights = [1.0] * len(modules)
    wsum = sum(weights)
    quotas = [available * w / wsum for w in weights]
    module_hours = largest_remainder(available, weights)
    # Модуль не может остаться без часов: забираем час у самого большого
    for i, h in enumerate(module_hours):
        if h == 0 and available >= len(modules):
            j = max(range(len(module_hours)), key=lambda k: module_hours[k])
            module_hours[j] -= 1
            module_hours[i] = 1

    lk_scale = 1.0
    srs_scale = 1.0
    for _attempt in range(30):
        rows: list[HoursRow] = []
        for m, h in zip(modules, module_hours, strict=True):
            if internship:
                rows.append(HoursRow(total=h, srs=h))
            else:
                rows.append(_split_kinds(h, m.lk_share * lk_scale, m.srs_share * srs_scale, m.lb_hours))
        practice = sum(r.pr for r in rows)
        if internship or practice >= min_practice_hours:
            break
        lk_scale *= 0.85
        srs_scale *= 0.8
    else:
        notes.append('Не удалось набрать требуемый минимум практики без нарушения структуры')
    if lk_scale < 1.0:
        notes.append(f'Доли лекций и СРС уменьшены, чтобы практика была не меньше {min_practice_hours} ч')

    out: list[ModuleOut] = []
    for m, row, q in zip(modules, rows, quotas, strict=True):
        topics = list(m.topics) or [TopicIn(title=m.title)]
        if len(topics) > row.total:
            topics = topics[: max(row.total, 1)]
            notes.append(f'Модуль «{m.title}»: тем больше, чем часов, лишние темы объединены')
        topic_rows = _split_topics(row, topics)
        out.append(
            ModuleOut(
                title=m.title,
                hours=row,
                topics=[(t.title, r) for t, r in zip(topics, topic_rows, strict=True)],
                quota=q,
                remainder=q - math.floor(q),
            )
        )

    totals = HoursRow()
    for mo in out:
        for k in ('total', *KINDS):
            setattr(totals, k, getattr(totals, k) + getattr(mo.hours, k))
    return SolverResult(modules=out, totals=totals, final_hours=final_hours, volume=volume, notes=notes)
