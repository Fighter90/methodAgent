"""Права и жизненный цикл по таблицам 19–21: 401 без токена, свои задания API-клиента, вычитка, откат, уведомления."""

from __future__ import annotations

import os
import time

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
    """Комплект методиста (не автопрогон): владелец u-madina."""
    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()['program_id']


def test_no_token_cannot_read_others(client, kit) -> None:
    """SPEC-AUTH-04, SPEC-EXPORT-10"""
    assert client.get(f'/api/v1/programs/{kit}').status_code == 401
    assert client.get(f'/api/v1/programs/{kit}/export/docx').status_code == 401
    assert all(p['id'] != kit for p in client.get('/api/v1/programs').json())


def test_auto_async_returns_202_and_job_result(client) -> None:
    """SPEC-API-06, SPEC-FLOW-02, SPEC-RULES-04"""
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ, 'wait': False})
    assert r.status_code == 202, r.text
    job = r.json()['job_id']
    for _ in range(200):
        info = client.get(f'/api/v1/jobs/{job}').json()
        if info['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert info['status'] == 'done', info
    assert info['result']['status'] in ('done', 'done_with_errors') and info['result']['report']['blocking_checks']


def test_expert_sees_only_own_modules_and_accepts_items(client, kit) -> None:
    """SPEC-API-12, SPEC-API-13, SPEC-API-14, SPEC-AUTH-08, SPEC-EXPORT-10, SPEC-FLOW-16, SPEC-FLOW-17, SPEC-FLOW-18"""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m1, m2 = doc['modules'][0]['id'], doc['modules'][1]['id']
    assert client.put(f'/api/v1/programs/{kit}/modules/{m1}/expert', json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    assert client.put(f'/api/v1/programs/{kit}/modules/{m2}/expert', json={'expert_id': 'u-olga'}, headers=hm).status_code == 200
    mine = client.get(f'/api/v1/programs/{kit}', headers=he).json()
    assert [m['id'] for m in mine['modules']] == [m1]
    assert {q['module_id'] for q in mine['kit']['questions']} == {m1}
    assert client.get(f'/api/v1/programs/{kit}/export/docx', headers=he).status_code == 403
    assert client.get(f'/api/v1/programs/{kit}/events', headers=he).status_code == 403
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    assert review['items_total'] > 1 and review['items_done'] == 0
    first = mine['kit']['questions'][0]['id']
    r = client.post(f'/api/v1/reviews/{review["rid"]}/decision', json={'decision': 'accept_item', 'node_id': first}, headers=he)
    assert r.status_code == 200, r.text
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    assert review['items_done'] == 1 and review['status'] == 'in_review'
    r = client.post(f'/api/v1/reviews/{review["rid"]}/comments', json={'text': 'Уточните формулировку'}, headers=he)
    assert r.status_code == 200
    notes = client.get('/api/v1/notifications', headers=hm).json()
    assert any('Уточните' in n['text'] for n in notes)
    assert client.post('/api/v1/notifications/read', json={}, headers=hm).json()['marked'] >= 1


def test_restore_does_not_bring_back_approval(client, kit) -> None:
    """SPEC-API-11, SPEC-API-12, SPEC-FLOW-22"""
    hm = _h(client, 'u-madina')
    from app.programs.schemas import Status

    vs = client.get(f'/api/v1/programs/{kit}/versions', headers=hm).json()
    r = client.post(f'/api/v1/programs/{kit}/versions/{vs[0]["version"]}/restore', headers=hm)
    assert r.status_code == 200
    assert r.json()['status'] not in (Status.APPROVED, Status.ON_APPROVAL)
    ev = client.get(f'/api/v1/programs/{kit}/events', headers=hm).json()
    assert ev[0]['action'] == 'restore' and ev[0]['before'] and ev[0]['version'] > 1


def test_json_export_follows_schema_48(client, kit) -> None:
    """SPEC-EXPORT-04"""
    import json

    hm = _h(client, 'u-madina')
    data = json.loads(client.get(f'/api/v1/programs/{kit}/export/json', headers=hm).content)
    prog = data['program']
    assert {'id', 'type', 'volume_h', 'competencies', 'modules', 'questions', 'tasks', 'lectures', 'final_assessment'} <= set(prog)
    assert 'usage' not in prog and 'params' not in prog
    assert prog['competencies'][0]['indicators'][0]['outcomes']
    assert {'total', 'lk', 'pr', 'lb', 'srs'} == set(prog['modules'][0]['hours'])


def test_edit_hours_keeps_module_total_and_text_edit_finds_target(client, kit) -> None:
    """SPEC-AUTH-09, SPEC-FLOW-13, SPEC-FLOW-14"""
    hm = _h(client, 'u-madina')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m = doc['modules'][0]
    t = m['topics'][0]
    want = {'srs': t['hours']['srs'] + 1}
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want, 'dry_run': True}, headers=hm)
    assert r.status_code == 200 and 'Тема' in r.json()['preview']['after']
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want}, headers=hm)
    if r.status_code == 409:
        assert r.json()['code'] in ('HOURS_MISMATCH', 'EDIT_REJECTED')
    else:
        after = r.json()['program']['modules'][0]
        assert after['hours']['total'] == m['hours']['total']
        assert sum(x['hours']['total'] for x in after['topics']) == m['hours']['total']
    word = t['title'].split()[0]
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': '', 'instruction': f'{word}: добавить пример', 'dry_run': True}, headers=hm)
    assert r.status_code == 200 and r.json()['target']
    he = _h(client, 'u-timur')
    assert client.post(f'/api/v1/programs/{kit}/edits', json={'target': f'hours:{t["id"]}', 'hours': want}, headers=he).status_code == 403


def test_module_accept_requires_all_items(client, kit) -> None:
    """SPEC-API-02, SPEC-API-13, SPEC-FLOW-17"""
    he = _h(client, 'u-timur')
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json())
    r = client.post(f'/api/v1/reviews/{review["rid"]}/decision', json={'decision': 'accept'}, headers=he)
    assert r.status_code == 409 and r.json()['code'] == 'ITEMS_NOT_CHECKED'


def test_expert_accepts_every_item_type_without_500(client, kit) -> None:
    """SPEC-API-34: эксперт отмечает проверенным элемент любого типа своего модуля — рабочую программу,
    тему, лекцию (в том числе по слайду и пункту плана), вопрос и задание (в том числе по критерию) —
    и ни один тип элемента не даёт 500; ожидаемое «не могу принять» — 404 с русским текстом,
    чужой элемент модулю не приписывается, после всех элементов модуль принимается с оценкой."""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    full = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m1 = full['modules'][0]['id']
    assert client.put(f'/api/v1/programs/{kit}/modules/{m1}/expert', json={'expert_id': 'u-timur'}, headers=hm).status_code == 200
    mine = client.get(f'/api/v1/programs/{kit}', headers=he).json()
    rid = next(r['rid'] for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)

    def decide(node: str):
        return client.post(f'/api/v1/reviews/{rid}/decision', json={'decision': 'accept_item', 'node_id': node}, headers=he)

    lecs = [x for x in mine['kit']['lectures'] if x['module_id'] == m1]
    slides = [s['id'] for lec in lecs for s in lec.get('slides') or []]
    plan_points = [f'{lec["id"]}#p1' for lec in lecs if lec.get('plan')]
    questions = [x['id'] for x in mine['kit']['questions'] if x.get('module_id') == m1]
    tasks = [x['id'] for x in mine['kit']['tasks'] if x.get('module_id') == m1]
    criteria = [f'{t}#c1' for t in tasks]
    topics = [t['id'] for t in mine['modules'][0]['topics']]
    foreign_q = next(q['id'] for q in full['kit']['questions'] if q.get('module_id') != m1)

    # слайд и пункт плана относятся к своей лекции, тема и фрагменты — к своему элементу
    for node in [*topics, *slides, *plan_points, *criteria, *[f'mp-{m1}'], *[lec['id'] for lec in lecs], *questions, *tasks]:
        r = decide(node)
        assert r.status_code == 200, f'{node}: {r.status_code} {r.text[:200]}'
    # чужой вопрос, неизвестный и пустой идентификатор — 404 с русским текстом, не 500
    for node in (foreign_q, 'nope-123', ''):
        r = decide(node)
        assert r.status_code == 404, f'{node!r}: {r.status_code} {r.text[:200]}'
        assert r.json()['code'] == 'NOT_FOUND' and 'Элемент' in r.json()['message_ru']
    # все элементы отмечены, модуль принимается с оценкой
    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    assert review['items_done'] == review['items_total'] > 0
    r = client.post(f'/api/v1/reviews/{rid}/decision', json={'decision': 'accept', 'score': 5}, headers=he)
    assert r.status_code == 200, r.text
    doc = client.get(f'/api/v1/programs/{kit}', headers=he).json()
    assert next(m for m in doc['modules'] if m['id'] == m1)['review_status'] == 'accepted'
    # данные комплекта в неожиданном формате (None вместо списка) — 400 с русским текстом, не 500
    from app.agent import workflow as wf
    from app.core.errors import BadRequest
    from app.programs.schemas import Kit, Module, ProgramDoc, Question_

    broken = ProgramDoc(id='prg-broken', request='запрос',
                        modules=[Module(id='m1', n=1, title='Модуль', expert_id='u-timur')],
                        kit=Kit(questions=[Question_(id='q1', assessment_id='test', module_id='m1', stem='s', options=['а', 'б'], key=0)]))
    broken.module_by_id('m1').accepted_items = None
    with pytest.raises(BadRequest, match='Не удалось принять решение'):
        wf.review_decision(broken, 'm1', 'u-timur', 'accept_item', node_id='q1')


def test_admin_profile_registry_and_expert_suggestions(client, kit) -> None:
    """SPEC-FLOW-29, SPEC-API-35, SPEC-KB-14, SPEC-KB-15, SPEC-SKILLS-09"""
    ha, hm = _h(client, 'u-admin'), _h(client, 'u-madina')
    assert client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 36}}, headers=hm).status_code == 403
    r = client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 36, 'form': 'очная'}}, headers=ha)
    assert r.status_code == 200 and r.json()['defaults']['volume_h'] == 36
    from app.skills.clarify.run import default_for

    assert default_for('volume_h') == 36
    assert client.put('/api/v1/org/profile', json={'bogus': 1}, headers=ha).status_code == 400
    items = client.get('/api/v1/org/registry?kind=tools', headers=ha).json()
    assert items
    ps = client.get('/api/v1/org/registry?kind=ps', headers=ha).json()
    r = client.put('/api/v1/org/registry', json={'kind': 'ps', 'items': ps}, headers=ha)
    assert r.status_code == 200 and r.json()['items'] == len(ps)
    assert all(x.get('checked_at') for x in client.get('/api/v1/org/registry?kind=ps', headers=ha).json())
    sug = client.get(f'/api/v1/programs/{kit}/experts', headers=hm).json()
    assert sug['experts'] and sug['suggestions'] == []  # MET-7: на стенде одни демо-учётки — подсказок нет
    assert 'подходящих экспертов нет' in sug['note'].lower()
    r = client.post('/api/v1/admin/users', json={'login': 'nina', 'name': 'Нина Смирнова', 'password': 'expert123',
                                                 'roles': ['expert'], 'title': 'Эксперт-преподаватель'}, headers=ha)
    assert r.status_code == 201, r.text
    nina = r.json()['id']
    sug = client.get(f'/api/v1/programs/{kit}/experts', headers=hm).json()
    # MET-7 (демо-прогон 19.10): подсказывает только реального активного эксперта, демо-учётки не подсказываются
    assert sug['suggestions'] and {s['expert_id'] for s in sug['suggestions']} == {nina}
    assert all(s['expert_id'] not in ('u-timur', 'u-olga') for s in sug['suggestions'])
    client.put('/api/v1/org/profile', json={'defaults': {'volume_h': 72, 'form': 'очно-заочная'}}, headers=ha)


def test_head_sees_quality_and_owners(client, kit) -> None:
    """SPEC-FLOW-20, SPEC-FLOW-21"""
    hh = _h(client, 'u-ahmed')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hh).json()
    q = doc['quality']
    assert {'human_edit_share', 'accepted_without_edits', 'expert_score', 'code_ok_share', 'work_days', 'generation_rub'} <= set(q)
    assert all(o['owner'] for o in doc['readiness']['open'])
    assert any('эксперт' in o['owner'] for o in doc['readiness']['open'])


def test_unassigned_expert_cannot_accept_and_api_404(client, kit) -> None:
    """SPEC-API-01, SPEC-API-05, SPEC-AUTH-09, SPEC-FLOW-17"""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    free = next((m for m in doc['modules'] if not m['expert_id']), None)
    if free:
        r = client.post(f'/api/v1/programs/{kit}/reviews/decision', json={'module_id': free['id'], 'decision': 'accept'}, headers=he)
        assert r.status_code == 403
    mine = next(m for m in doc['modules'] if m['expert_id'] == 'u-timur')
    r = client.post(f'/api/v1/programs/{kit}/reviews/decision', json={'module_id': mine['id'], 'decision': 'accept'}, headers=he)
    if r.status_code == 409:
        assert r.json()['details']['missing']
    r = client.get('/api/v1/no-such-method')
    assert r.status_code == 404 and r.headers['content-type'].startswith('application/json')
    assert client.get('/api/v1/health').json()['status'] == 'ok'


def test_expert_node_must_belong_to_own_module(client, kit) -> None:
    """SPEC-AUTH-30: подмена node_id чужого задания отвергается на каждом пути эксперта —
    в комментарии, в запросе предложения агенту и в применении правки; чужой модуль не меняется."""
    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    doc = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    version_before = doc['version']
    m1 = next(m['id'] for m in doc['modules'] if m['expert_id'] == 'u-timur')
    foreign = next(q for q in doc['kit']['questions'] if q['module_id'] != m1)
    own_q = next(q for q in doc['kit']['questions'] if q['module_id'] == m1)
    # 1) комментарий со своим module_id и чужим node_id — 403, в том числе с запросом правки агенту
    r = client.post(f'/api/v1/programs/{kit}/comments', json={'module_id': m1, 'text': 'Правка чужого', 'node_id': foreign['id']}, headers=he)
    assert r.status_code == 403, r.text
    r = client.post(f'/api/v1/programs/{kit}/comments', json={'module_id': m1, 'text': 'Правка чужого', 'node_id': foreign['id'], 'ask_agent': True}, headers=he)
    assert r.status_code == 403, r.text
    # 2) комментарий к своему вопросу работает
    r = client.post(f'/api/v1/programs/{kit}/comments', json={'module_id': m1, 'text': 'Уточните формулировку', 'node_id': own_q['id']}, headers=he)
    assert r.status_code == 200, r.text
    # 3) применение правки по чужому node_id: комментарий методиста с чужим узлом не даёт эксперту править чужой модуль
    r = client.post(f'/api/v1/programs/{kit}/comments', json={'module_id': m1, 'text': 'Внедрить чужое', 'node_id': foreign['id'], 'ask_agent': True}, headers=hm)
    assert r.status_code == 200, r.text
    cid = r.json()['comment']['id']
    r = client.post(f'/api/v1/programs/{kit}/comments/answer', json={'comment_id': cid, 'apply_proposal': True}, headers=he)
    assert r.status_code == 403, r.text
    after = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    fq = next(q for q in after['kit']['questions'] if q['id'] == foreign['id'])
    assert fq['stem'] == foreign['stem'] and fq['options'] == foreign['options']  # чужое задание не изменилось
    assert after['version'] == version_before  # версия комплекта не менялась правками эксперта


def test_expert_view_filters_foreign_content(client, kit) -> None:
    """SPEC-API-32, SPEC-AUTH-08: во всех ответах эксперту (GET программы, разделы, приёмка элемента,
    точечная правка) нет чужих модулей и общих текстов с их содержанием; методисту — всё как раньше."""
    import json as _json

    hm, he = _h(client, 'u-madina'), _h(client, 'u-timur')
    full = client.get(f'/api/v1/programs/{kit}', headers=hm).json()
    m1 = next(m['id'] for m in full['modules'] if m['expert_id'] == 'u-timur')
    foreign_m = next(m for m in full['modules'] if m['id'] != m1)
    marker_q = next(q for q in full['kit']['questions'] if q['module_id'] != m1)['stem']  # уникальная метка чужого комплекта
    marker_topic = foreign_m['topics'][0]['title']  # метка чужой темы в общих текстах

    mine = client.get(f'/api/v1/programs/{kit}', headers=he)
    assert mine.status_code == 200
    data = mine.json()
    assert {m['id'] for m in data['modules']} == {m1}
    assert marker_q not in _json.dumps(data, ensure_ascii=False)
    assert marker_topic not in _json.dumps(data, ensure_ascii=False)  # и в календарном расписании тоже
    assert not (data['kit']['sections'].get('annotation') or data['kit']['sections'].get('content'))

    secs = client.get(f'/api/v1/programs/{kit}/sections', headers=he).json()
    texts = {s['key']: s['text'] for s in secs}
    assert not texts.get('annotation') and not texts.get('content')
    assert marker_topic not in ' '.join(texts.values())
    secs_m = client.get(f'/api/v1/programs/{kit}/sections', headers=hm).json()
    assert marker_topic in ' '.join(s['text'] for s in secs_m)  # методисту тексты остаются

    review = next(r for r in client.get('/api/v1/reviews', headers=he).json() if r['module_id'] == m1)
    own_item = next(q['id'] for q in data['kit']['questions'] if q['module_id'] == m1)
    r = client.post(f'/api/v1/reviews/{review["rid"]}/decision', json={'decision': 'accept_item', 'node_id': own_item}, headers=he)
    assert r.status_code == 200, r.text
    assert marker_q not in r.text and marker_topic not in r.text

    own_q = next(q for q in data['kit']['questions'] if q['module_id'] == m1)
    r = client.post(f'/api/v1/programs/{kit}/edits', json={'target': own_q['id'], 'instruction': 'уточнить формулировку', 'dry_run': True}, headers=he)
    assert r.status_code == 200, r.text
    assert marker_q not in r.text

    # правка по замечанию: комментарий эксперта к своему вопросу, применение — ответ без чужого содержания
    r = client.post(f'/api/v1/programs/{kit}/comments', json={'module_id': m1, 'text': 'Поправьте формулировку', 'node_id': own_q['id'], 'ask_agent': True}, headers=he)
    assert r.status_code == 200, r.text
    cid = r.json()['comment']['id']
    r = client.post(f'/api/v1/programs/{kit}/comments/answer', json={'comment_id': cid, 'apply_proposal': True}, headers=he)
    assert r.status_code == 200, r.text
    assert marker_q not in r.text and marker_topic not in r.text


def test_approve_atomic_capacity_first_and_idempotent_job(client, monkeypatch) -> None:
    """SPEC-API-31, SPEC-SVC-14: утверждение каркаса резервирует ёмкость и задание до изменения состояния:
    при 429 каркас остаётся в предыдущем состоянии, повторное утверждение возвращает то же активное задание."""
    import asyncio

    from app.agent import workflow as wf
    from app.core.config import get_settings
    from app.programs import service as svc
    from app.skills.clarify.run import DEFAULT_ANSWER

    h = _h(client, 'u-madina')
    r = client.post('/api/v1/programs', json={'request': REQ}, headers=h)
    body = r.json()
    assert r.status_code == 200, r.text
    pid = body['program_id']
    if body.get('needs_answers'):
        ans = {q['id']: DEFAULT_ANSWER for q in body['questions']}
        r = client.post(f'/api/v1/programs/{pid}/answers?wait=true', json={'answers': ans}, headers=h)
        assert r.status_code == 200, r.text
    assert client.get(f'/api/v1/programs/{pid}', headers=h).json()['status'] == 'skeleton'
    # снимаем пункты «!», чтобы утверждение было доступно (как auto-approve в автопрогоне)
    rep = client.get(f'/api/v1/programs/{pid}/report', headers=h).json()
    for pr in [p for p in rep.get('proposals', []) if not p.get('decided')]:
        client.post(f'/api/v1/programs/{pid}/skeleton/decisions',
                    json={'rule_id': pr['rule_id'], 'decision': 'accept', 'node': pr.get('node', ''),
                          'proposal': pr.get('proposal', ''), 'option_id': pr.get('option_id', '')}, headers=h)
    # 1) исчерпанная ёмкость: 429 приходит до изменения состояния каркаса
    limit = get_settings().max_parallel_jobs
    monkeypatch.setattr(svc, '_tasks', {object() for _ in range(limit)})
    r = client.post(f'/api/v1/programs/{pid}/skeleton/approve', json={'decision': 'approve'}, headers=h)
    assert r.status_code == 429, r.text
    assert client.get(f'/api/v1/programs/{pid}', headers=h).json()['status'] == 'skeleton'
    # 2) двойное утверждение: задание одно, повтор возвращает тот же job_id (идемпотентность)
    real_gen = wf.generate_kit

    async def slow_gen(doc, progress=None):
        await asyncio.sleep(0.4)  # задание остаётся активным на время второго запроса
        return await real_gen(doc, progress)

    monkeypatch.setattr(svc, '_tasks', set())
    monkeypatch.setattr(wf, 'generate_kit', slow_gen)
    r1 = client.post(f'/api/v1/programs/{pid}/skeleton/approve', json={'decision': 'approve'}, headers=h)
    assert r1.status_code == 202, r1.text
    job1 = r1.json()['job_id']
    r2 = client.post(f'/api/v1/programs/{pid}/skeleton/approve', json={'decision': 'approve'}, headers=h)
    assert r2.status_code == 202, r2.text
    assert r2.json()['job_id'] == job1
    for _ in range(200):
        info = client.get(f'/api/v1/jobs/{job1}', headers=h).json()
        if info['status'] in ('done', 'failed'):
            break
        time.sleep(0.05)
    assert info['status'] == 'done', info
    assert client.get(f'/api/v1/programs/{pid}', headers=h).json()['status'] == 'kit_ready'
