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
    assert client.get(f'/api/v1/programs/{program}').status_code == 200
    r = client.post('/api/v1/programs', json={'request': REQ})
    assert r.status_code == 401
    r = client.post('/api/v1/programs/upload', data={'text': REQ})
    assert r.status_code == 401


def test_adapt_keeps_competencies_and_resolves_hours(client, program) -> None:
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
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs', json={'request': REQ, 'answers': {}}, headers=h)
    pid = r.json()['program_id']
    st = client.get(f'/api/v1/programs/{pid}').json()['status']
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
    from app.agent.extras import scan_text

    found = scan_text('Используем Python 2.7 и df.append, PostgreSQL 12, ChatGPT для проверки. Иванов И. Учебник. — М., 2009. — 300 с.')
    kinds = {f['kind'] for f in found}
    assert {'construct', 'version', 'service', 'source'} <= kinds
    r = client.get(f'/api/v1/programs/{program}/actualize', headers=_h(client, 'u-madina'))
    assert r.status_code == 200 and 'findings' in r.json()
    up = client.post('/api/v1/actualize', files={'file': ('old.txt', io.BytesIO('Тема 3. pandas 1.5 и Python 3.7'.encode()), 'text/plain')}, headers=_h(client, 'u-madina'))
    assert up.status_code == 200 and up.json()['total'] >= 2


def test_versions_diff_and_sections(client, program) -> None:
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
    r = client.get(f'/api/v1/programs/{program}/sandbox', headers=_h(client, 'u-madina'))
    assert r.status_code == 200 and 'items' in r.json()
    t = client.get('/api/v1/me/tasks', headers=_h(client, 'u-ahmed')).json()
    assert set(t['tasks']) == {'methodist', 'expert', 'head'}


def test_head_filter(client, program) -> None:
    r = client.get('/api/v1/programs?status=on_approval,approved', headers=_h(client, 'u-ahmed'))
    assert r.status_code == 200 and all(p['status'] in ('on_approval', 'approved') for p in r.json())


def test_kb_upload_and_search(client) -> None:
    text = 'Положение о дополнительном образовании. Итоговая аттестация проводится в форме защиты проекта. Объём программы не менее 16 часов.'
    r = client.post('/api/v1/kb/documents', files={'file': ('polozhenie.txt', io.BytesIO(text.encode()), 'text/plain')}, data={'kind': 'regulation'}, headers=_h(client, 'u-admin'))
    assert r.status_code == 200, r.text
    assert client.post('/api/v1/kb/documents', files={'file': ('x.txt', io.BytesIO(b'abc'), 'text/plain')}, headers=_h(client, 'u-madina')).status_code == 403
    hits = client.post('/api/v1/kb/search', json={'query': 'итоговая аттестация защита проекта'}, headers=_h(client, 'u-madina')).json()
    assert hits and hits[0]['name'] == 'polozhenie.txt'


def test_skeleton_guards() -> None:
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
    from app.kb.registry import literature_for, match_source

    assert match_source('GitLab Docs')['id'] == 'lit-gitlab-ci-docs'
    kids = [s.id for s in literature_for('Python для школьников, анализ данных pandas', school=True)]
    assert 'lit-mckinney' not in kids and 'lit-python-docs' in kids


def test_interview_questions_vary(client, program) -> None:
    from app.agent.workflow import interview_questions
    from app.programs.schemas import ProgramDoc

    doc = ProgramDoc.model_validate(client.get(f'/api/v1/programs/{program}').json())
    qs = [q for m in doc.modules for q in interview_questions(doc, m)]
    starts = {q.split('«')[0] for q in qs}
    assert len(starts) >= 4


def test_parse_json_truncated_reasoning() -> None:
    import json

    from app.llm.client import parse_json

    assert parse_json('<think>шаг {1}</think>{"verdicts": []}') == {'verdicts': []}
    with pytest.raises(json.JSONDecodeError):
        parse_json('<think>долго {"x": 1} и обрыв')
