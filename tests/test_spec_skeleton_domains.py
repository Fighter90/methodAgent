"""Релевантность библиотеки направлений запросу (SPEC-SKILLS-19, аудит 19.10 F06)."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.programs.schemas import Params, ProgramType  # noqa: E402

DISABLED = SimpleNamespace(enabled=False)


def _run(monkeypatch, params: Params, stats=None):
    from app.skills.skeleton import run as sk

    monkeypatch.setattr(sk, 'get_llm', lambda: DISABLED)
    return asyncio.run(sk.run(params, ProgramType.DPP_PK, None, [], stats))


def _all_text(draft) -> str:
    return ' '.join(
        [draft.goal, *(m.title for m in draft.modules), *(t.title + ' ' + t.description for m in draft.modules for t in m.topics)],
    ).lower()


def test_postgresql_gets_no_pandas(monkeypatch) -> None:
    """SPEC-SKILLS-19: запрос про администрирование PostgreSQL не получает тем pandas, визуализации и статистики."""
    from app.skills.skeleton.library import pick_domain
    from app.skills.skeleton.run import ensure_topics, must_cover

    params = Params(
        volume_h=72, title='Администрирование баз данных PostgreSQL', direction='PostgreSQL',
        audience='ИТ-специалисты', required_topics=['резервное копирование', 'репликация'],
    )
    text = ' '.join([params.title, params.direction, params.audience, *params.required_topics]).lower()
    assert pick_domain(text) is None  # 'sql' внутри 'postgresql' домен анализа данных не открывает
    assert must_cover(params) == []  # и «обязательных» тем pandas у каркаса нет
    draft = _run(monkeypatch, params)
    assert draft.source == 'generic'  # каркас собран по запросу, а не по чужому домену
    full = _all_text(draft)
    assert 'pandas' not in full and 'статистик' not in full and 'визуализац' not in full and 'matplotlib' not in full
    assert 'postgresql' in full  # предмет запроса остался в каркасе
    n_topics = len([t for m in draft.modules for t in m.topics])
    ensure_topics(draft, must_cover(params))  # наложение на каркас модели тоже ничего не меняет
    assert len([t for m in draft.modules for t in m.topics]) == n_topics


def test_docker_exam_task_is_about_docker(monkeypatch) -> None:
    """SPEC-SKILLS-19: итоговый экзамен по Docker — задание про Docker, без «атаки» и отчёта о стажировке."""
    params = Params(
        volume_h=36, title='Подготовка к итоговому экзамену по Docker', direction='Docker',
        audience='инженеры', final_assessment_form='Экзамен',
    )
    draft = _run(monkeypatch, params)
    final = draft.modules[-1]
    text = ' '.join([final.title, final.control, *(t.title + ' ' + t.description for t in final.topics)]).lower()
    assert 'docker' in text  # итоговое задание от предмета запроса
    assert 'атак' not in text and 'уязвим' not in text and 'стажировк' not in text
    assert 'экзамен' in final.control.lower()


def test_java_reserve_stays_java(monkeypatch) -> None:
    """SPEC-SKILLS-19: в резерве «Java для школьников» не превращается в Python — каркас по универсальному шаблону."""
    from app.llm.client import CallStats

    params = Params(
        volume_h=16, title='Java для школьников', direction='Java',
        audience='школьники 8–9 классов', final_assessment_form='Защита проекта',
    )
    stats = CallStats()
    draft = _run(monkeypatch, params, stats)
    assert draft.source == 'generic'
    full = _all_text(draft)
    assert 'python' not in full and 'питон' not in full
    assert 'java' in full  # направление запроса сохранено
    assert any('направление из библиотеки не найдено' in f['fallback'] for f in stats.fallbacks)


def test_pandas_request_keeps_pandas(monkeypatch) -> None:
    """SPEC-SKILLS-19: pandas-запрос получает домен анализа данных, и названные темы остаются обязательными."""
    from app.skills.skeleton.run import ensure_topics, must_cover

    params = Params(
        volume_h=72, title='Анализ данных на Python', direction='анализ данных',
        audience='сотрудники банков', required_topics=['pandas', 'визуализация', 'SQL', 'статистика'],
    )
    must = must_cover(params)
    assert [row[0] for row in must] == ['Обработка данных в pandas', 'Визуализация данных', 'SQL для аналитика', 'Основы статистики']
    draft = _run(monkeypatch, params)  # резерв: домен сохраняет темы запроса
    assert draft.source == 'data_analysis' and 'pandas' in _all_text(draft)
    for m in draft.modules:  # если модель пропустила названную тему, ensure_topics возвращает её
        m.title = 'Другое'
        for t in m.topics:
            t.title, t.description = 'Другое', ''
    ensure_topics(draft, must)
    assert any('pandas' in t.title.lower() for m in draft.modules for t in m.topics)


def test_must_covers_only_named_topics() -> None:
    """SPEC-SKILLS-19: домен распознан, но навязываются только темы, названные в запросе."""
    from app.skills.skeleton.run import must_cover

    params = Params(volume_h=36, title='Основы pandas для аналитиков', direction='анализ данных', required_topics=['pandas'])
    must = must_cover(params)
    assert [row[0] for row in must] == ['Обработка данных в pandas']  # SQL и статистику запрос не называет
