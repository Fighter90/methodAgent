"""Сценарии сверх основного потока: шаблон, адаптация, актуализация, версии, песочница, роли, база знаний, доступ без токена."""

from __future__ import annotations

import io
import os

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture(scope='module')
def program(client) -> str:
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ})
    assert r.status_code == 200
    return r.json()['program_id']


def test_anonymous_limited_to_auto_and_reads(client, program) -> None:
    """SPEC-AUTH-04"""
    assert client.get(f'/api/v1/programs/{program}').status_code == 200
    r = client.post('/api/v1/programs', json={'request': REQ})
    assert r.status_code == 401
    r = client.post('/api/v1/programs/upload', data={'text': REQ})
    assert r.status_code == 401


def test_adapt_keeps_competencies_and_resolves_hours(client, program) -> None:
    """SPEC-FLOW-25, SPEC-SOLVER-04"""
    src = client.get(f'/api/v1/programs/{program}').json()
    r = client.post(f'/api/v1/programs/{program}/adapt', json={'volume_h': 36, 'audience': 'аналитики малого бизнеса'}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
    doc = r.json()['program']
    assert doc['id'] != program and doc['status'] == 'skeleton'
    assert [c['id'] for c in doc['competencies']] == [c['id'] for c in src['competencies']]
    total = sum(m['hours']['total'] for m in doc['modules']) + doc['final_assessment']['hours']
    assert total == 36
    assert doc['params']['audience'] == 'аналитики малого бизнеса'


def test_change_template_before_approval(client) -> None:
    """SPEC-FLOW-24, SPEC-SOLVER-07"""
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs', json={'request': REQ, 'answers': {}}, headers=h)
    pid = r.json()['program_id']
    st = client.get(f'/api/v1/programs/{pid}', headers=h).json()['status']
    if st == 'questions':
        import time

        job = client.post(f'/api/v1/programs/{pid}/answers', json={'answers': {}}, headers=h).json()['job_id']
        for _ in range(100):
            if client.get(f'/api/v1/jobs/{job}', headers=h).json()['status'] in ('done', 'failed'):
                break
            time.sleep(0.1)
    r = client.post(f'/api/v1/programs/{pid}/template', json={'program_type': 'dpp_pk_internship'}, headers=h)
    assert r.status_code == 200, r.text
    doc = r.json()['program']
    assert doc['type'] == 'dpp_pk_internship'
    assert all(m['hours']['lk'] == 0 and m['hours']['pr'] == 0 for m in doc['modules'])


def test_actualize_text_and_program(client, program) -> None:
    """SPEC-API-18, SPEC-FLOW-26"""
    from app.agent.extras import scan_text

    found = scan_text('Используем Python 2.7 и df.append, PostgreSQL 12, ChatGPT для проверки. Иванов И. Учебник. — М., 2009. — 300 с.')
    kinds = {f['kind'] for f in found}
    assert {'construct', 'version', 'service', 'source'} <= kinds
    r = client.get(f'/api/v1/programs/{program}/actualize', headers=_h(client, 'u-madina'))
    assert r.status_code == 200 and 'findings' in r.json()
    up = client.post('/api/v1/actualize', files={'file': ('old.txt', io.BytesIO('Тема 3. pandas 1.5 и Python 3.7'.encode()), 'text/plain')}, headers=_h(client, 'u-madina'))
    assert up.status_code == 200 and up.json()['total'] >= 2


def test_versions_diff_and_sections(client, program) -> None:
    """SPEC-API-10, SPEC-API-11, SPEC-FLOW-23, SPEC-FLOW-30"""
    h = _h(client, 'u-madina')
    vs = client.get(f'/api/v1/programs/{program}/versions', headers=h).json()
    assert len(vs) >= 2
    d = client.get(f'/api/v1/programs/{program}/versions/{vs[-1]["version"]}/diff/{vs[0]["version"]}', headers=h)
    assert d.status_code == 200 and 'changes' in d.json()
    secs = client.get(f'/api/v1/programs/{program}/sections').json()
    titles = [s['title'] for s in secs]
    assert '2.5.1. Форма(ы) текущей, промежуточной и итоговой аттестации' in titles
    assert '3.2.5. Программное обеспечение и информационные системы' in titles
    assert titles[-1] == 'Приложение 2'


def test_sandbox_and_tasks(client, program) -> None:
    """SPEC-API-15, SPEC-FLOW-27, SPEC-FLOW-28"""
    r = client.get(f'/api/v1/programs/{program}/sandbox', headers=_h(client, 'u-madina'))
    assert r.status_code == 200 and 'items' in r.json()
    t = client.get('/api/v1/me/tasks', headers=_h(client, 'u-ahmed')).json()
    assert set(t['tasks']) == {'methodist', 'expert', 'head'}


def test_head_filter(client, program) -> None:
    """SPEC-API-09"""
    r = client.get('/api/v1/programs?status=on_approval,approved', headers=_h(client, 'u-ahmed'))
    assert r.status_code == 200 and all(p['status'] in ('on_approval', 'approved') for p in r.json())


def test_kb_upload_and_search(client) -> None:
    """SPEC-API-23, SPEC-KB-09, SPEC-KB-10"""
    text = 'Положение о дополнительном образовании. Итоговая аттестация проводится в форме защиты проекта. Объём программы не менее 16 часов.'
    r = client.post('/api/v1/kb/documents', files={'file': ('polozhenie.txt', io.BytesIO(text.encode()), 'text/plain')}, data={'kind': 'regulation'}, headers=_h(client, 'u-admin'))
    assert r.status_code == 200, r.text
    assert client.post('/api/v1/kb/documents', files={'file': ('x.txt', io.BytesIO(b'abc'), 'text/plain')}, headers=_h(client, 'u-madina')).status_code == 403
    hits = client.post('/api/v1/kb/search', json={'query': 'итоговая аттестация защита проекта'}, headers=_h(client, 'u-madina')).json()
    assert hits and hits[0]['name'] == 'polozhenie.txt'


def test_skeleton_guards() -> None:
    """SPEC-SKILLS-12"""
    from app.programs.schemas import Module, Params, Topic
    from app.skills.skeleton.run import (
        SkeletonDraft,
        drop_assessment_modules,
        ensure_topics,
        must_cover,
    )

    mods = [
        Module(id=f'm{i}', n=i, title=t, weight=0.2, topics=[Topic(id=f't{i}.1', n=f'{i}.1', title=t)])
        for i, t in enumerate(['Администрирование Linux', 'Контейнеризация Docker', 'Конвейеры CI/CD', 'Итоговая аттестация и защита отчёта'], start=1)
    ]
    draft = SkeletonDraft(title='DevOps', goal='', competencies=[], modules=mods, source='llm')
    drop_assessment_modules(draft)
    assert [m.title for m in draft.modules][-1] == 'Конвейеры CI/CD' and draft.modules[-1].id == 'm3'
    must = must_cover(Params(title='DevOps-инженер от Linux до CI/CD', direction='DevOps'))
    ensure_topics(draft, must)
    text = ' '.join(t.title for m in draft.modules for t in m.topics).lower()
    assert 'инфраструктура как код' in text and 'мониторинг' in text


def test_v13_repair_adds_question(client, program) -> None:
    from app.programs.schemas import ProgramDoc
    from app.validation.repair import cover_outcomes
    from app.validation.rules import assessment_map

    doc = ProgramDoc.model_validate(client.get(f'/api/v1/programs/{program}').json())
    lo = doc.all_outcomes()[0]
    doc.kit.questions = [q for q in doc.kit.questions if lo.id not in q.lo_ids]
    for t in doc.kit.tasks:
        if t.assessment_id != 'final':
            t.lo_ids = [x for x in t.lo_ids if x != lo.id]
    assert len(assessment_map(doc)[lo.id]) < 2
    log = cover_outcomes(doc)
    assert log and len(assessment_map(doc)[lo.id]) >= 2


def test_judge_merge_and_title_cap() -> None:
    from app.agent.workflow import _cap
    from app.programs.schemas import ProgramDoc, Report, RuleResult
    from app.validation.judge import merge

    assert _cap('кибербезопасность для студентов') == 'Кибербезопасность для студентов'
    doc = ProgramDoc(id='p', request='x')
    doc.kit.judge = {'V-21': ['Тема 2.1 опирается на циклы из темы 3.1']}
    rep = Report(stage='kit', rules=[RuleResult(id='V-21', title='', check=None, kind='llm', status='pass')])
    merge(doc, rep)
    assert rep.rules[0].status == 'warn' and rep.rules[0].messages[0].startswith('Судья:')


def test_sources_school_and_generic_docs() -> None:
    """SPEC-KB-08"""
    from app.kb.registry import literature_for, match_source

    assert match_source('GitLab Docs')['id'] == 'lit-gitlab-ci-docs'
    kids = [s.id for s in literature_for('Python для школьников, анализ данных pandas', school=True)]
    assert 'lit-mckinney' not in kids and 'lit-python-docs' in kids


def test_interview_questions_vary(client, program) -> None:
    """SPEC-FLOW-31"""
    from app.agent.workflow import interview_questions
    from app.programs.schemas import ProgramDoc

    doc = ProgramDoc.model_validate(client.get(f'/api/v1/programs/{program}').json())
    qs = [q for m in doc.modules for q in interview_questions(doc, m)]
    starts = {q.split('«')[0] for q in qs}
    assert len(starts) >= 4


def test_parse_json_truncated_reasoning() -> None:
    """SPEC-LLM-01: оборванный блок рассуждения не мешает разбору JSON."""
    import json

    from app.llm.client import parse_json

    assert parse_json('<think>шаг {1}</think>{"verdicts": []}') == {'verdicts': []}
    with pytest.raises(json.JSONDecodeError):
        parse_json('<think>долго {"x": 1} и обрыв')


def test_blocked_services_scrubbed() -> None:
    """SPEC-CONTENT-11: сервисы, недоступные в России, вычищаются из текста."""
    from app.skills.content.run import ModuleContentLLM, scrub_blocked

    data = ModuleContentLLM.model_validate({
        'annotation': 'Сравним ChatGPT и GigaChat',
        'questions': [
            {'stem': 'Какой сервис доступен в России?', 'options': ['ChatGPT', 'YandexGPT', 'DeepMind', 'Bard'], 'key': 1},
            {'stem': 'Что такое промпт?', 'options': ['Запрос к модели', 'Файл', 'Вирус', 'Диск'], 'key': 0},
        ],
    })
    out = scrub_blocked(data)
    assert 'ChatGPT' not in out.annotation and [q.stem for q in out.questions] == ['Что такое промпт?']


def test_daily_limit_fails_fast(tmp_path, monkeypatch) -> None:
    """SPEC-LLM-11: 429 «суточный лимит» не повторяется и не идёт в резерв; перегрузка шлюза — повторяется."""
    import asyncio

    from app.llm import client as c

    class Limit(c.GatewayError):
        def __init__(self) -> None:
            super().__init__('HTTP 429', 429, {'code': 'llm_daily_limit_exceeded', 'message': 'daily spending limit is reached'})

    class Busy(c.GatewayError):
        def __init__(self) -> None:
            super().__init__('HTTP 429', 429)

    assert c.is_daily_limit(Limit()) and not c.is_daily_limit(Busy())
    llm = c.LLMClient()
    monkeypatch.setattr(llm.settings, 'data_dir', tmp_path)
    monkeypatch.setattr(type(llm), 'enabled', property(lambda self: True))
    calls = []

    class Fake:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw['model'])
                    raise Limit()

    llm._client = Fake()
    with pytest.raises(c.LLMUnavailable, match='лимит'):
        asyncio.run(llm.complete_json(skill='t', system='s', user='u'))
    assert len(calls) == 1 and llm.limit_reached()
    with pytest.raises(c.LLMUnavailable):
        asyncio.run(llm.complete_json(skill='t', system='s', user='u'))
    assert len(calls) == 1  # второй вызов даже не идёт в шлюз
    reloaded = c.LLMClient()
    monkeypatch.setattr(reloaded.settings, 'data_dir', tmp_path)
    reloaded._load_spend()
    assert reloaded.limit_reached()  # переживает перезапуск контейнера


def test_budget_day_is_moscow(monkeypatch) -> None:
    """SPEC-LLM-15: сутки расхода считаются по Москве."""
    from app.llm import client as c

    monkeypatch.setattr(c.time, 'time', lambda: 1760738400.0)  # 2025-10-17 22:00 UTC = 18.10 01:00 МСК
    assert c._today() == '2025-10-18'


def test_cyrillic_txt_cut_at_2000_bytes_is_text():
    """SPEC-KB-11"""
    from app.kb.files import detect_format

    body = ('я' * 999 + 'ж' * 10).encode('utf-8')  # 2000-й байт приходится на середину буквы
    assert detect_format(b'a' + body) == 'txt'
    assert detect_format(b'\xff\xfe\x00bin') is None


def test_skills_list_endpoint(client) -> None:
    """SPEC-API-16, SPEC-SKILLS-01"""
    r = client.get('/api/v1/skills')
    assert r.status_code == 200 and any(s['name'] == 'skeleton' for s in r.json())


def test_kb_docx_zip_bomb_rejected_and_normal_ok() -> None:
    """SPEC-KB-13"""
    import io
    import zipfile

    from docx import Document as DocxDocument

    from app.core.errors import BadRequest
    from app.kb.files import parse_reference

    # Обычный маленький docx разбирается
    ok_buf = io.BytesIO()
    DocxDocument().save(ok_buf)
    ref = parse_reference('normal.docx', ok_buf.getvalue())
    assert ref.name == 'normal.docx'

    # DOCX, распакованное содержимое которого больше 100 МБ, отклоняется (zip-бомба)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('word/document.xml', b'0' * (101 * 1024 * 1024))
    with pytest.raises(BadRequest):
        parse_reference('bomb.docx', bomb.getvalue())


def test_tool_aliases_from_registry() -> None:
    """SPEC-SKILLS-18"""
    from app.agent import extras
    from app.kb.registry import tools

    reg = tools()
    assert 'постгрес' in reg['aliases']['postgresql'] and 'k8s' in reg['aliases']['kubernetes']
    found = {f['found'] for f in extras.scan_text('Курс на постгрес 12 и k8s 1.30, а также питон 3.8')}
    assert any('постгрес' in x.lower() for x in found), found
    assert any('k8s' in x.lower() for x in found), found
    assert any('питон' in x.lower() for x in found), found
    # Новый инструмент или псевдоним добавляется в реестр — распознавание меняется без правки кода
    reg2 = {**reg,
            'current': {**reg['current'], 'mynewdb': '2.0'},
            'min_supported': {**reg.get('min_supported', {}), 'mynewdb': '1.5'},
            'aliases': {**reg['aliases'], 'mynewdb': ['mynewdb', 'муньюдб']}}
    monkeypatch.setattr(extras, 'tools', lambda: reg2)
    found2 = extras.scan_text('Используем муньюдб 1.0')
    assert any('муньюдб' in f['found'].lower() for f in found2), found2
