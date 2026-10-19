"""Спецификации skills-core.md, agent-workflow.md, api.md, auth-and-roles.md: требования без собственного тестового модуля."""

from __future__ import annotations

import asyncio
import base64
import importlib
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.core.errors import Conflict  # noqa: E402
from app.programs.schemas import (  # noqa: E402
    Competency,
    Indicator,
    LearningOutcome,
    Module,
    Params,
    ProgramDoc,
    ProgramType,
    Report,
    Status,
    Topic,
)

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')
DISABLED = SimpleNamespace(enabled=False)


class FakeLLM:
    """Модель-заглушка: отдаёт заранее заданный JSON и запоминает запросы."""

    enabled = True

    def __init__(self, data: dict) -> None:
        self.data = data
        self.calls: list[dict] = []

    async def complete_json(self, **kw):
        self.calls.append(kw)
        return kw['schema'].model_validate(self.data)


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.kb.registry import registry

    registry.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture(scope='module')
def kit(client) -> str:
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
    return r.json()['program_id']


def _load(client, pid: str) -> ProgramDoc:
    from app.programs import service as svc

    return client.portal.call(svc.load, pid)


def _skel_doc(vague: bool = False) -> ProgramDoc:
    """Каркас ДООП без ошибок: часы от солвера, календарь, отчёт этапа skeleton."""
    from app.agent import workflow as wf
    from app.validation.report import build_report

    los = [LearningOutcome(id='lo1', code='РО 1', text='Понимает циклы' if vague else 'Пишет циклы'),
           LearningOutcome(id='lo2', code='РО 2', text='Пишет функции')]
    doc = ProgramDoc(
        id='p', request='x', type=ProgramType.DOOP, status=Status.SKELETON, goal='Цель', title='Python',
        params=Params(volume_h=16, final_assessment_form='Зачёт', final_assessment_hours=2),
        competencies=[Competency(id='c1', code='К-1', title='К', indicators=[Indicator(id='i1', kind='can', text='x', outcomes=los)])],
    )
    mods = [Module(id='m1', n=1, title='Циклы', weight=1, topics=[Topic(id='t1.1', n='1.1', title='Цикл for', lo_ids=['lo1'])]),
            Module(id='m2', n=2, title='Функции', weight=1, topics=[Topic(id='t2.1', n='2.1', title='Функции', lo_ids=['lo2'])])]
    wf.apply_solver(doc, mods)
    wf.plan_doc_calendar(doc)
    doc.report = build_report(doc, 'skeleton')
    return doc


# --------------------------------------------------------------------------- skills-core.md
def test_unknown_skill(client) -> None:
    """SPEC-SKILLS-04: неизвестный навык — KeyError в коде и 404 в API."""
    from app.skills.base import skill

    with pytest.raises(KeyError):
        skill('no-such-skill')
    assert skill('skeleton').name == 'skeleton'
    r = client.put('/api/v1/admin/skills/no-such-skill', json={'temperature': 0.1}, headers=_h(client, 'u-admin'))
    assert r.status_code == 404 and r.json()['code'] == 'NOT_FOUND'


def test_intake_heuristics_without_llm(monkeypatch) -> None:
    """SPEC-SKILLS-06: без модели аудитория, входной уровень и темы определяются эвристиками по тексту запроса."""
    intake = importlib.import_module('app.skills.intake.run')
    monkeypatch.setattr(intake, 'get_llm', lambda: DISABLED)
    text = 'Курс по Python на 36 часов для менеджеров проектов без опыта программирования. Темы: переменные, циклы и функции.'
    params, used = asyncio.run(intake.run(text))
    assert used is False
    assert params.audience == 'менеджеров проектов'
    assert params.entry_level == 'Без опыта программирования'
    assert params.required_topics == ['переменные', 'циклы', 'функции']
    assert params.volume_h == 36


def test_classify_type_template_norms_ps() -> None:
    """SPEC-SKILLS-07: тип — из параметров, иначе по словам «школьник», «детей» — ДООП; шаблон, документ, НПА и ПС (только ДПП)."""
    from app.skills.classify.run import run

    doop = run('Курс робототехники для школьников 5–7 классов', Params())
    assert doop.program_type == ProgramType.DOOP and doop.template == 'ДООП'
    assert doop.issued_document == 'Сертификат об освоении программы'
    assert doop.profstandard is None and doop.norm_base
    unknown = run('Курс по анализу данных', Params())
    assert unknown.program_type is None and 'не ясен' in unknown.message
    dpp = run('Курс по анализу данных на Python для аналитиков', Params(program_type=ProgramType.DPP_PK, direction='анализ данных'))
    assert dpp.program_type == ProgramType.DPP_PK and dpp.template == 'ДПП ПК'
    assert dpp.issued_document == 'Удостоверение о повышении квалификации'
    assert dpp.profstandard is not None and dpp.norm_base
    # Явный тип из параметров важнее слов запроса
    assert run('Курс для детей', Params(program_type=ProgramType.DPP_PK)).program_type == ProgramType.DPP_PK


def test_clarify_questions_only_for_missing() -> None:
    """SPEC-SKILLS-08: не больше 5 вопросов, только по пустым обязательным полям, каждый — с вариантами ответа."""
    from app.skills.clarify.run import run

    qs = run(Params())
    assert len(qs) == 5
    assert all(q.options for q in qs)
    full = Params(program_type=ProgramType.DPP_PK, volume_h=72, audience='Аналитики', entry_level='Знают Excel', form='очная',
                  final_assessment_form='Зачёт')
    assert run(full) == []
    part = run(full.model_copy(update={'form': '', 'volume_h': None}))
    assert [q.field for q in part] == ['volume_h', 'form']


def test_skeleton_llm_structure_limits(monkeypatch) -> None:
    """SPEC-SKILLS-10: от модели — только структура и веса: до 8 компетенций, 12 модулей, 8 тем, доли ЛК и СРС в 0–0.6; часы — солверу."""
    sk = importlib.import_module('app.skills.skeleton.run')
    data = {
        'title': 'Python', 'goal': 'Цель',
        'competencies': [{'title': f'Компетенция {i}', 'indicators': [{'kind': 'can', 'text': 'Умеет', 'outcomes': [{'code': f'{i}.1', 'text': f'Пишет код {i}'}]}]}
                         for i in range(1, 11)],
        'modules': [{'title': f'Модуль {i}', 'weight': 1, 'lk_share': 0.9, 'srs_share': -0.2,
                     'topics': [{'title': f'Тема {i}.{j}', 'weight': 1, 'lo': ['1.1']} for j in range(1, 11)]} for i in range(1, 16)],
    }
    fake = FakeLLM(data)
    monkeypatch.setattr(sk, 'get_llm', lambda: fake)
    draft = asyncio.run(sk.run(Params(volume_h=72, title='Python'), ProgramType.DOOP, None, []))
    assert draft.source == 'llm'
    assert len(draft.competencies) == 8 and len(draft.modules) == 12
    assert all(len(m.topics) == 8 for m in draft.modules)
    assert all(m.lk_share == 0.6 and m.srs_share == 0.0 for m in draft.modules)
    assert all(m.hours.total == 0 and t.hours.total == 0 for m in draft.modules for t in m.topics)
    assert 'hours' not in sk.ModuleLLM.model_fields and 'hours' not in sk.TopicLLM.model_fields


def test_skeleton_fallback_library(monkeypatch) -> None:
    """SPEC-SKILLS-13: модель недоступна или вернула меньше двух модулей — каркас из библиотеки доменов или общего шаблона."""
    sk = importlib.import_module('app.skills.skeleton.run')
    monkeypatch.setattr(sk, 'get_llm', lambda: DISABLED)
    params = Params(volume_h=72, title='Анализ данных на Python', required_topics=['pandas', 'визуализация'])
    lib = asyncio.run(sk.run(params, ProgramType.DPP_PK, None, []))
    assert lib.source not in ('llm', 'generic') and len(lib.modules) >= 2
    generic = asyncio.run(sk.run(Params(volume_h=36, title='Гончарное ремесло', required_topics=['глина', 'обжиг']), ProgramType.DOOP, None, []))
    assert generic.source == 'generic' and len(generic.modules) >= 2
    one = {'title': 'x', 'goal': 'y', 'competencies': [{'title': 'К', 'indicators': [{'text': 'Пишет код'}]}],
           'modules': [{'title': 'Один модуль', 'topics': [{'title': 'Тема'}]}]}
    monkeypatch.setattr(sk, 'get_llm', lambda: FakeLLM(one))
    fb = asyncio.run(sk.run(params, ProgramType.DPP_PK, None, []))
    assert fb.source != 'llm' and len(fb.modules) >= 2


def test_link_outcomes_both_ways() -> None:
    """SPEC-SKILLS-14: каждый РО связан хотя бы с одной темой, каждая тема — хотя бы с одним РО."""
    from app.skills.skeleton.run import SkeletonDraft, link_outcomes

    los = [LearningOutcome(id=f'lo{i}', code=f'РО {i}', text=t) for i, t in enumerate(['Пишет циклы for', 'Читает файлы CSV', 'Строит графики'], 1)]
    draft = SkeletonDraft(
        title='x', goal='y', source='llm',
        competencies=[Competency(id='c1', code='ПК-1', title='К', indicators=[Indicator(id='i1', kind='can', text='x', outcomes=los)])],
        modules=[Module(id='m1', n=1, title='М', topics=[Topic(id=f't{i}', n=str(i), title=t) for i, t in
                                                         enumerate(['Циклы for и while', 'Файлы CSV', 'Повторение', 'Итоги'], 1)])],
    )
    link_outcomes(draft)
    topics = draft.modules[0].topics
    assert all(t.lo_ids for t in topics)
    assert {lo for t in topics for lo in t.lo_ids} == {'lo1', 'lo2', 'lo3'}
    assert 'lo1' in topics[0].lo_ids and 'lo2' in topics[1].lo_ids


# --------------------------------------------------------------------------- agent-workflow.md
def test_auto_run_exception_marks_failed(client, monkeypatch) -> None:
    """SPEC-FLOW-04: автопрогон, прерванный исключением, переводит программу в статус failed."""
    from app.programs import router

    async def boom(doc, owner):
        raise RuntimeError('сбой')

    monkeypatch.setattr(router, '_auto_pipeline', boom)
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=h)
    assert r.status_code == 200 and r.json()['status'] == 'failed'
    doc = client.get(f'/api/v1/programs/{r.json()["program_id"]}', headers=h).json()
    assert doc['status'] == 'failed'
    assert any('Сборка прервана: RuntimeError' in n for n in doc['agent_notes'])


def test_patch_skeleton_locked() -> None:
    """SPEC-FLOW-07: правка каркаса не в статусе skeleton или returned отклоняется (SKELETON_LOCKED)."""
    from app.agent import workflow as wf

    for st in (Status.SKELETON_APPROVED, Status.KIT_READY, Status.ON_APPROVAL):
        doc = _skel_doc()
        doc.status = st
        with pytest.raises(Conflict) as e:
            wf.patch_skeleton(doc, {'goal': 'Новая цель'})
        assert e.value.code == 'SKELETON_LOCKED'
    doc = _skel_doc()
    doc.status = Status.RETURNED
    wf.patch_skeleton(doc, {'goal': 'Новая цель'})
    assert doc.goal == 'Новая цель'


def test_approve_skeleton_errors_and_pending() -> None:
    """SPEC-FLOW-09: fail в отчёте каркаса — SKELETON_HAS_ERRORS; нерешённые предложения в интерактивном режиме — DECISIONS_PENDING."""
    from app.agent import workflow as wf
    from app.validation.report import build_report

    bad = _skel_doc()
    bad.modules[0].hours.total += 1
    bad.report = build_report(bad, 'skeleton')
    with pytest.raises(Conflict) as e:
        wf.approve_skeleton(bad, 'u-madina')
    assert e.value.code == 'SKELETON_HAS_ERRORS'

    vague = _skel_doc(vague=True)
    assert [p['rule_id'] for p in vague.report.proposals] == ['V-22']
    with pytest.raises(Conflict) as e:
        wf.approve_skeleton(vague, 'u-madina')
    assert e.value.code == 'DECISIONS_PENDING'
    wf.decide(vague, 'V-22', 'keep', 'u-madina', node='lo1')
    wf.approve_skeleton(vague, 'u-madina')
    assert vague.status == Status.SKELETON_APPROVED
    # в режиме auto предложения принимаются автоматически
    auto = _skel_doc(vague=True)
    wf.approve_skeleton(auto, 'auto-approve', auto=True)
    assert auto.status == Status.SKELETON_APPROVED and not auto.all_outcomes()[0].text.startswith('Понимает')


def test_generate_requires_approved_skeleton() -> None:
    """SPEC-FLOW-10: пока каркас не утверждён, комплект не генерируется (SKELETON_NOT_APPROVED)."""
    from app.agent import workflow as wf

    for st in (Status.DRAFT, Status.QUESTIONS, Status.SKELETON, Status.RETURNED):
        doc = _skel_doc()
        doc.status = st
        with pytest.raises(Conflict) as e:
            asyncio.run(wf.generate_kit(doc))
        assert e.value.code == 'SKELETON_NOT_APPROVED'
        assert doc.status == st and not doc.kit.questions


def test_return_with_comment_passes_current_skeleton(monkeypatch) -> None:
    """SPEC-FLOW-11: при возврате с комментарием модель получает текущий каркас и комментарий; без модели каркас не заменяется, методисту — заметка."""
    from app.agent import workflow as wf

    sk = importlib.import_module('app.skills.skeleton.run')
    doc = _skel_doc()
    doc.norm_fragments = [{'name': 'x', 'text': 'y'}]  # нормативная база уже подобрана
    before = [m.model_dump() for m in doc.modules]
    monkeypatch.setattr(sk, 'get_llm', lambda: DISABLED)
    asyncio.run(wf.skeleton_step(doc, comment='Добавьте тему про словари'))
    assert [m.model_dump() for m in doc.modules] == before
    assert any('Комментарий «Добавьте тему про словари» не обработан' in n for n in doc.agent_notes)

    import json

    data = {'title': 'Python', 'goal': 'Цель 2',
            'competencies': [{'title': 'К', 'indicators': [{'text': 'Умеет', 'outcomes': [{'code': '1.1', 'text': 'Пишет циклы'}]}]}],
            'modules': [{'title': 'Циклы', 'weight': 1, 'topics': [{'title': 'Цикл for', 'lo': ['1.1']}]},
                        {'title': 'Словари', 'weight': 1, 'topics': [{'title': 'Словари', 'lo': ['1.1']}]}]}
    fake = FakeLLM(data)
    monkeypatch.setattr(sk, 'get_llm', lambda: fake)
    asyncio.run(wf.skeleton_step(doc, comment='Добавьте тему про словари'))
    payload = json.loads(fake.calls[0]['user'])
    assert payload['methodist_comment'] == 'Добавьте тему про словари'
    assert [m['title'] for m in payload['current_skeleton']['modules']] == ['Циклы', 'Функции']
    assert [m.title for m in doc.modules] == ['Циклы', 'Словари']


def test_edit_rollback_and_new_version(client, kit) -> None:
    """SPEC-FLOW-15: при разошедшихся часах правка откатывается целиком (EDIT_REJECTED); успешная — новая версия и возврат принятого модуля на вычитку."""
    from app.agent import workflow as wf

    doc = _load(client, kit)
    task = doc.kit.tasks[0]
    module = doc.module_by_id(task.module_id)
    module.hours.total += 1  # часы модуля разошлись
    snapshot = doc.model_dump()
    with pytest.raises(Conflict) as e:
        client.portal.call(wf.edit, doc, task.id, 'Уточнить условие задачи')
    assert e.value.code == 'EDIT_REJECTED' and 'не сходятся' in e.value.message_ru
    after = doc.model_dump()
    assert after.pop('progress') != snapshot.pop('progress')  # пишется только отметка о проверке
    assert after == snapshot

    doc = _load(client, kit)
    task = doc.kit.tasks[0]
    module = doc.module_by_id(task.module_id)
    module.review_status = 'accepted'
    module.accepted_items = [task.id]
    res = client.portal.call(wf.edit, doc, task.id, 'Добавить критерий: оформление отчёта')
    assert res['applied'] and task.id in res['changed']
    assert module.review_status == 'in_review' and task.id not in module.accepted_items

    h = _h(client, 'u-madina')
    v0 = client.get(f'/api/v1/programs/{kit}', headers=h).json()['version']
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': task.id, 'instruction': 'Добавить критерий: сроки'}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()['program']['version'] > v0


def test_submit_and_head_decision() -> None:
    """SPEC-FLOW-19: отправка — при 10/10 и всех принятых модулях; утверждение — при индексе готовности 100 %; возврат — только с комментарием."""
    from app.agent import workflow as wf

    doc = _skel_doc()
    doc.status = Status.KIT_READY
    doc.report = Report(stage='kit', blocking_passed=9, blocking_total=10)
    with pytest.raises(Conflict) as e:
        wf.submit(doc, 'u-madina')
    assert e.value.code == 'BLOCKING_FAILED'
    doc.report.blocking_passed = 10
    doc.modules[0].review_status = 'accepted'
    with pytest.raises(Conflict) as e:
        wf.submit(doc, 'u-madina')
    assert e.value.code == 'MODULES_NOT_ACCEPTED' and e.value.details['modules'] == [2]
    doc.modules[1].review_status = 'accepted'
    wf.submit(doc, 'u-madina')
    assert doc.status == Status.ON_APPROVAL

    doc.report.blocking_passed = 9
    with pytest.raises(Conflict) as e:
        wf.head_decision(doc, 'u-olga', 'approve')
    assert e.value.code == 'NOT_READY'
    with pytest.raises(Conflict) as e:
        wf.head_decision(doc, 'u-olga', 'return', '  ')
    assert e.value.code == 'COMMENT_REQUIRED'
    doc.report.blocking_passed = 10
    assert wf.readiness(doc)['index'] == 100
    wf.head_decision(doc, 'u-olga', 'approve')
    assert doc.status == Status.APPROVED

    doc.status = Status.ON_APPROVAL
    wf.head_decision(doc, 'u-olga', 'return', 'Доработать модуль 2')
    assert doc.status == Status.RETURNED and doc.approvals[-1].comment == 'Доработать модуль 2'


def test_sources_confirmed_or_marked() -> None:
    """SPEC-FLOW-32: источники из реестра подтверждаются, остальные помечаются «[не подтверждено]»."""
    from app.agent import workflow as wf

    doc = _skel_doc()
    doc.type = ProgramType.DPP_PK
    wf._sources(doc, ['Документация Python 3 — https://docs.python.org/3/', 'Неизвестный А. Тайная книга о квазарах. 2024'])
    py = next(s for s in doc.sources if 'docs.python.org' in s.url)
    assert py.confirmed
    unknown = next(s for s in doc.sources if 'квазар' in s.bibl)
    assert not unknown.confirmed and unknown.bibl.endswith('[не подтверждено]')
    assert all(s.confirmed or '[не подтверждено]' in s.bibl for s in doc.sources)


def test_norm_and_org_fragments(monkeypatch) -> None:
    """SPEC-FLOW-33: в каркас идут до 4 выдержек НПА и (режим org) до 4 фрагментов документов организации; акты и документы — в нормативную базу."""
    import json

    from app.agent import extras

    doc = ProgramDoc(id='p', request=REQ, type=ProgramType.DPP_PK,
                     params=Params(title='Анализ данных на Python', form='очно-заочная', volume_h=72))
    hits = extras.apply_norms(doc)
    assert 0 < len(doc.norm_fragments) <= 4 and len(hits) == len(doc.norm_fragments)
    assert any(s.kind == 'law' for s in doc.norm_base)

    calls = {}

    async def fake_search(query, k=5):
        calls['k'] = k
        return [{'doc_id': f'd{i}', 'chunk': 0, 'name': f'Положение {i}', 'text': f'Текст {i}'} for i in range(k)]

    monkeypatch.setattr(extras.orgdocs, 'search', fake_search)
    monkeypatch.setattr(extras.orgdocs, 'templates', lambda: [])
    org = ProgramDoc(id='p', request=REQ, type=ProgramType.DPP_PK, norm_mode='org')
    asyncio.run(extras.apply_org_docs(org))
    assert calls['k'] == 4 and len(org.org_fragments) == 4
    assert {s.id for s in org.norm_base if s.kind == 'doc'} == {'d0', 'd1', 'd2', 'd3'}

    sk = importlib.import_module('app.skills.skeleton.run')
    data = {'competencies': [{'title': 'К', 'indicators': [{'text': 'Пишет код'}]}],
            'modules': [{'title': 'А', 'topics': [{'title': 'а'}]}, {'title': 'Б', 'topics': [{'title': 'б'}]}]}
    fake = FakeLLM(data)
    monkeypatch.setattr(sk, 'get_llm', lambda: fake)
    many = [{'name': f'n{i}', 'text': 't'} for i in range(7)]
    asyncio.run(sk.run(Params(volume_h=72), ProgramType.DPP_PK, None, [], org_documents=many, norm_documents=many))
    payload = json.loads(fake.calls[0]['user'])
    assert len(payload['org_documents']) == 4 and len(payload['norm_documents']) == 4


@pytest.mark.parametrize(('volume', 'limit', 'option'), [(72, ', не больше 4 часов в день', 'six_days'), (144, '', 'extend')])
def test_auto_calendar_conflict_choice(client, volume: int, limit: str, option: str) -> None:
    """SPEC-FLOW-34: в режиме auto при конфликте календаря выбирается six_days при максимуме часов в день, иначе extend; выбор — в допущениях."""
    req = f'Программа повышения квалификации на {volume} часа по Python для аналитиков, очно, за 1 неделю{limit}. Итоговая аттестация — защита проекта.'
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs?mode=auto', json={'request': req}, headers=h)
    assert r.status_code == 200, r.text
    doc = client.get(f'/api/v1/programs/{r.json()["program_id"]}', headers=h).json()
    assert doc['calendar']['conflict'] and doc['calendar']['chosen_option'] == option
    assert {'field': 'calendar', 'value': option} in [{k: a[k] for k in ('field', 'value')} for a in doc['assumptions']]


# --------------------------------------------------------------------------- api.md
def test_unhandled_error_hides_details() -> None:
    """SPEC-API-04: необработанное исключение — 500 INTERNAL_ERROR без внутренних деталей."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.errors import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get('/boom')
    async def boom():
        raise RuntimeError('пароль БД: secret123')

    r = TestClient(app, raise_server_exceptions=False).get('/boom')
    assert r.status_code == 500
    assert r.json() == {'code': 'INTERNAL_ERROR', 'message_ru': 'Внутренняя ошибка сервера', 'details': {}}
    assert 'secret123' not in r.text


def test_request_limits(client, monkeypatch) -> None:
    """SPEC-API-08: запрос 5–5000 символов, до 5 вложений не больше MAX_FILE_SIZE_MB; нарушения — 400 или 422."""
    from app.core.config import get_settings

    h = _h(client, 'u-madina')
    url = '/api/v1/programs'
    assert client.post(url, json={'request': 'abcd'}, headers=h).status_code == 422
    assert client.post(url, json={'request': 'я' * 5001}, headers=h).status_code == 422
    att = {'name': 'a.txt', 'content_base64': base64.b64encode(b'hello').decode()}
    assert client.post(url, json={'request': REQ, 'attachments': [att] * 6}, headers=h).status_code == 422
    monkeypatch.setattr(get_settings(), 'max_file_size_mb', 0)
    r = client.post(url, json={'request': REQ, 'attachments': [att]}, headers=h)
    assert r.status_code == 400 and 'больше 0 МБ' in r.json()['message_ru']


def test_parallel_jobs_limit(client, monkeypatch) -> None:
    """SPEC-API-19: превышение MAX_PARALLEL_JOBS — 429 RATE_LIMIT."""
    from app.core.config import get_settings
    from app.programs import service as svc

    monkeypatch.setattr(svc, '_tasks', set(range(get_settings().max_parallel_jobs)))
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ, 'wait': False}, headers=_h(client, 'u-madina'))
    assert r.status_code == 429 and r.json()['code'] == 'RATE_LIMIT'


def test_resume_jobs_on_start(client) -> None:
    """SPEC-API-20: при старте задания, прерванные перезапуском, продолжаются (неизвестный вид — закрывается с ошибкой)."""
    from app.programs import service as svc
    from app.programs.router import resume_jobs

    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs', json={'request': REQ}, headers=h)
    pid = r.json()['program_id']
    job = client.portal.call(svc.create_job, pid, 'skeleton')
    odd = client.portal.call(svc.create_job, pid, 'unknown-kind')
    assert client.portal.call(resume_jobs) >= 1
    for _ in range(200):
        info = client.get(f'/api/v1/jobs/{job}', headers=h).json()
        if info['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert info['status'] == 'done', info
    bad = client.get(f'/api/v1/jobs/{odd}', headers=h).json()
    assert bad['status'] == 'failed' and 'перезапуском' in bad['error']


def test_cors_and_docs(client, monkeypatch) -> None:
    """SPEC-API-21: CORS для всех источников; Swagger UI по /docs, пока включена DOCS_ENABLED."""
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    r = client.options('/api/v1/health', headers={'Origin': 'https://example.org', 'Access-Control-Request-Method': 'GET'})
    assert r.status_code == 200 and r.headers['access-control-allow-origin'] in ('*', 'https://example.org')
    assert client.get('/api/v1/health', headers={'Origin': 'https://a.b'}).headers['access-control-allow-origin'] == '*'
    docs = client.get('/docs')
    assert get_settings().docs_enabled and docs.status_code == 200 and 'swagger-ui' in docs.text
    monkeypatch.setattr(get_settings(), 'docs_enabled', False)
    off = TestClient(create_app()).get('/docs')
    assert 'swagger-ui' not in off.text  # без DOCS_ENABLED Swagger UI не публикуется (404 или страница интерфейса)


def test_llm_status(client) -> None:
    """SPEC-API-22: /llm/status — доступность шлюза, расход за день, дневной бюджет, признак исчерпания лимита и модели."""
    j = client.get('/api/v1/llm/status').json()
    assert {'spent_today_rub', 'daily_budget_rub', 'daily_limit_reached', 'models'} <= set(j)
    assert set(j['models']) == {'generate', 'judge', 'embed'}
    assert isinstance(j['daily_limit_reached'], bool)
    assert any(k in j for k in ('available', 'ok', 'status', 'enabled'))


# --------------------------------------------------------------------------- auth-and-roles.md
def test_anon_rate_limit(client, monkeypatch) -> None:
    """SPEC-AUTH-05: анонимный клиент сверх anon_runs_per_hour автопрогонов в час с одного IP получает 429 RATE_LIMIT."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), 'anon_runs_per_hour', 0)
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers={'X-Forwarded-For': '203.0.113.7'})
    assert r.status_code == 429 and r.json()['code'] == 'RATE_LIMIT'
    # с токеном лимит анонимов не действует
    assert client.post('/api/v1/programs', json={'request': 'abc'}, headers=_h(client, 'u-madina')).status_code == 422


def test_demo_account_cannot_change_profile(client) -> None:
    """SPEC-AUTH-14: демо-учётка не меняет свой профиль и пароль — 403."""
    h = _h(client, 'u-madina')
    assert client.put('/api/v1/auth/me', json={'name': 'Другое имя'}, headers=h).status_code == 403
    r = client.put('/api/v1/auth/me/password', json={'current': 'demo', 'new': 'Newpass123'}, headers=h)
    assert r.status_code == 403


def test_passwords_bcrypt_only(client) -> None:
    """SPEC-AUTH-17: пароли хранятся только хешем bcrypt."""
    import bcrypt

    from app.core.db import UserRow, sessionmaker

    ha = _h(client, 'u-admin')
    r = client.post('/api/v1/admin/users', json={'login': 'ivan17', 'name': 'Иван', 'password': 'Ivan12345', 'roles': ['expert']}, headers=ha)
    assert r.status_code == 201, r.text
    uid = r.json()['id']
    assert 'password' not in r.json() and 'password_hash' not in r.json()

    async def _hash() -> str:
        async with sessionmaker()() as s:
            return (await s.get(UserRow, uid)).password_hash

    stored = client.portal.call(_hash)
    assert stored.startswith('$2') and 'Ivan12345' not in stored
    assert bcrypt.checkpw(b'Ivan12345', stored.encode())


def test_secret_unreadable(monkeypatch) -> None:
    """SPEC-AUTH-19: секрет, зашифрованный другим SECRET_KEY или повреждённый, не расшифровывается (SecretUnreadable)."""
    from app.core import crypto
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), 'secret_key', 'first-secret-key-0123456789')
    token = crypto.encrypt('sk-12345')
    assert crypto.decrypt(token) == 'sk-12345'
    broken = token[:-4] + ('AAAA' if not token.endswith('AAAA') else 'BBBB')
    with pytest.raises(crypto.SecretUnreadable):
        crypto.decrypt(broken)
    with pytest.raises(crypto.SecretUnreadable):
        crypto.decrypt('plain-text')
    monkeypatch.setattr(get_settings(), 'secret_key', 'other-secret-key-9876543210')
    with pytest.raises(crypto.SecretUnreadable):
        crypto.decrypt(token)


@pytest.mark.parametrize('weak', ['short', 'a-very-long-key-but-change-me-please'])
def test_weak_secret_key_replaced(tmp_path, weak: str) -> None:
    """SPEC-AUTH-22: SECRET_KEY короче 16 символов или с «change-me» заменяется случайным ключом из data_dir/.secret_key."""
    from app.core.config import Settings

    s = Settings(secret_key=weak, data_dir=tmp_path)
    stored = (tmp_path / '.secret_key').read_text(encoding='utf-8').strip()
    assert s.secret_key == stored and len(stored) == 64 and s.secret_key != weak
    assert Settings(secret_key=weak, data_dir=tmp_path).secret_key == stored  # ключ стабилен между запусками
    strong = 'a-strong-production-secret-1234'
    assert Settings(secret_key=strong, data_dir=tmp_path / 'other').secret_key == strong


def test_question_edit_keeps_lo_links(client, kit, monkeypatch) -> None:
    """SPEC-FLOW-41: WHEN правка переформулирует вопрос, а модель привязала новый вопрос к другому РО, THE SYSTEM SHALL сохранить прежние РО вопроса, чтобы правка не нарушала V-13 и не отклонялась."""
    from app.agent import workflow as wf

    content = importlib.import_module('app.skills.content.run')
    doc = _load(client, kit)
    q = doc.kit.questions[0]
    old_lo = list(q.lo_ids)
    other = next(lo.id for lo in doc.all_outcomes() if lo.id not in old_lo)
    real_run = content.run

    async def wrong_lo_run(*a, **kw):
        res = await real_run(*a, **kw)
        for nq in res.questions:
            nq.lo_ids = [other]
        return res

    monkeypatch.setattr(wf.content, 'run', wrong_lo_run)
    res = client.portal.call(wf.edit, doc, q.id, 'Сделать вопрос проще')
    assert res['applied']
    assert next(x for x in doc.kit.questions if x.id == q.id).lo_ids == old_lo
