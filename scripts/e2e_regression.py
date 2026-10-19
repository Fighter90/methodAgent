"""Сквозной регресс МетодАгента по HTTP API для всех ролей.

Проходит полный жизненный цикл программы на запущенном сервере: вход всех демо-учёток и разделение ролей,
интерактивное создание программы методистом (вопросы, «На ваше усмотрение», каркас, решения по «!»,
утверждение, комплект, правки, версии, шаблон, адаптация, актуализация, песочница, назначение экспертов),
вычитка экспертами, согласование у руководителя (возврат и утверждение), выгрузки всех форматов с проверкой
содержимого, администрирование и автопрогон открытых кейсов.

Запуск (сервер уже работает, например с LLM_PROVIDERS=fixtures):
    python scripts/e2e_regression.py                         # полный регресс + автопрогон всех 5 кейсов
    python scripts/e2e_regression.py --case 4                # интерактивный сценарий по кейсу 4, автопрогон только кейса 4
    python scripts/e2e_regression.py --all-cases             # интерактивный сценарий по каждому из 5 кейсов
    python scripts/e2e_regression.py --base http://host:8000

Печатает PASS/FAIL по каждому шагу и сводку; код выхода 1, если есть хотя бы один FAIL.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

API = '/api/v1'
PASSWORD = 'demo'
DEMO = {'madina': 'methodist', 'timur': 'expert', 'olga': 'expert', 'ahmed': 'head', 'admin': 'admin', 'api': 'api'}
BLANK = '________________'
# Обязательные НПА по кейсам (ДООП — 629, ДПП — 266)
MANDATORY_NPA = {1: {'law-273', 'order-629'}, 2: {'law-273', 'order-266'}, 3: {'law-273', 'order-266'},
                 4: {'law-273', 'order-266'}, 5: {'law-273', 'order-266'}}
TYPE_BY_CASE = {1: 'doop', 2: 'dpp_pk', 3: 'dpp_pk', 4: 'dpp_pk', 5: 'dpp_pk_internship'}
VOLUME_BY_CASE = {1: 16, 2: 36, 3: 72, 4: 72, 5: 256}


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []
        self.section = ''

    def head(self, title: str) -> None:
        self.section = title
        print(f'\n== {title}')

    def check(self, name: str, ok: bool, detail: Any = '') -> bool:
        label = f'[{self.section}] {name}'
        if ok:
            self.passed += 1
            print(f'PASS {label}')
        else:
            extra = f' — {detail}' if detail not in ('', None) else ''
            self.failed.append(label + extra)
            print(f'FAIL {label}{extra}')
        return ok


R = Results()


class Client:
    """HTTP-клиент с токеном роли: интерфейсные роли шлют X-MA-Token, API-клиент — Authorization: Bearer."""

    def __init__(self, http: httpx.Client, token: str | None = None, bearer: bool = False) -> None:
        self.http, self.token, self.bearer = http, token, bearer

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {'Authorization': f'Bearer {self.token}'} if self.bearer else {'X-MA-Token': self.token}

    def req(self, method: str, path: str, **kw: Any) -> httpx.Response:
        url = path if path.startswith('/health') else API + path
        return self.http.request(method, url, headers={**self._headers(), **kw.pop('headers', {})}, **kw)

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.req('GET', path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.req('POST', path, **kw)

    def put(self, path: str, **kw: Any) -> httpx.Response:
        return self.req('PUT', path, **kw)

    def patch(self, path: str, **kw: Any) -> httpx.Response:
        return self.req('PATCH', path, **kw)

    def delete(self, path: str, **kw: Any) -> httpx.Response:
        return self.req('DELETE', path, **kw)


def _body(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return r.text[:300]


def expect(name: str, r: httpx.Response, status: int | tuple[int, ...] = 200) -> Any:
    """Проверка статуса ответа; возвращает JSON (или None при несовпадении)."""
    want = status if isinstance(status, tuple) else (status,)
    ok = r.status_code in want
    body = _body(r)
    detail = '' if ok else f'HTTP {r.status_code}, ждали {"/".join(map(str, want))}: {str(body)[:300]}'
    R.check(name, ok, detail)
    return body if ok else None


def wait_job(c: Client, job_id: str, timeout: float = 900) -> dict[str, Any]:
    t0 = time.monotonic()
    info: dict[str, Any] = {}
    while time.monotonic() - t0 < timeout:
        r = c.get(f'/jobs/{job_id}')
        if r.status_code != 200:
            return {'status': 'http_error', 'error': f'HTTP {r.status_code}: {r.text[:200]}'}
        info = r.json()
        if info.get('status') in ('done', 'failed'):
            return info
        time.sleep(0.5)
    return {**info, 'status': 'timeout'}


def login(http: httpx.Client, login_: str, role: str | None = None) -> tuple[Client | None, dict[str, Any]]:
    body: dict[str, Any] = {'login': login_, 'password': PASSWORD}
    if role:
        body['role'] = role
    r = http.post(f'{API}/auth/login', json=body)
    data = expect(f'вход {login_}' + (f' ({role})' if role else ''), r)
    if not data:
        return None, {}
    bearer = data['user']['role'] == 'api'
    return Client(http, data['access_token'], bearer=bearer), data['user']


def step(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Запуск блока проверок: исключение в блоке — FAIL с трассой, остальные блоки продолжаются."""
    try:
        return fn(*args, **kw)
    except Exception as exc:  # noqa: BLE001 — регресс продолжается, падение блока фиксируется как FAIL
        R.check(f'блок {fn.__name__} без исключений', False, f'{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}')
        return None


def load_cases() -> list[dict[str, Any]]:
    return json.loads((ROOT / 'testset' / 'cases.json').read_text(encoding='utf-8'))


def attachments(case: dict[str, Any]) -> list[dict[str, str]]:
    return [{'name': Path(a).name, 'content_base64': base64.b64encode((ROOT / a).read_bytes()).decode()} for a in case['attachments']]


# --------------------------------------------------------------------------- 1. вход и роли
def auth_and_roles(http: httpx.Client) -> dict[str, Client]:
    R.head('Вход и разделение ролей')
    anon = Client(http)
    expect('GET /health', anon.get('/health'))
    cfg = expect('GET /auth/config', anon.get('/auth/config'))
    if cfg:
        R.check('форма входа показывает 6 демо-учёток', len(cfg.get('demo_accounts', [])) == 6, cfg.get('demo_accounts'))
    clients: dict[str, Client] = {}
    for user, role in DEMO.items():
        c, u = login(http, user)
        if c is None:
            continue
        R.check(f'{user}: роль в сессии {role}', u.get('role') == role, u.get('role'))
        me = expect(f'{user}: GET /auth/me', c.get('/auth/me'))
        if me:
            R.check(f'{user}: /auth/me роль {role}', me.get('role') == role, me)
        clients[user] = c
    expect('неверный пароль → 401', http.post(f'{API}/auth/login', json={'login': 'madina', 'password': 'wrong'}), 401)
    expect('битый токен → 401', Client(http, 'not-a-jwt').get('/programs'), 401)
    # API-клиент может работать и методистом (две роли)
    c_api_m, u = login(http, 'api', role='methodist')
    if c_api_m:
        R.check('api входит ролью methodist', u.get('role') == 'methodist')
    sw = expect('madina: switch-role на чужую роль → 403', clients['madina'].post('/auth/switch-role', json={'role': 'head'}), 403)
    _ = sw

    # Анонимный доступ: только автопрогон и чтение (SPEC-AUTH-04)
    expect('аноним: GET /auth/me → 401', anon.get('/auth/me'), 401)
    expect('аноним: POST /programs (interactive) → 401', anon.post('/programs', json={'request': 'Программа по Python, 16 часов'}), 401)
    expect('аноним: POST /programs/upload → 401', anon.post('/programs/upload', data={'text': 'Программа по Python'}), 401)
    expect('аноним: GET /admin/users → 401/403', anon.get('/admin/users'), (401, 403))
    expect('аноним: PUT /admin/settings → 401', anon.put('/admin/settings', json={'values': {}}), 401)
    expect('аноним: POST /kb/search → 401', anon.post('/kb/search', json={'query': 'закон об образовании'}), 401)
    expect('аноним: GET /me/tasks → 401', anon.get('/me/tasks'), 401)
    lst = expect('аноним: GET /programs (как api) → 200', anon.get('/programs'))
    if lst is not None:
        R.check('аноним видит только программы u-api', all(x.get('owner', 'u-api') == 'u-api' for x in lst), lst[:3])
    expect('аноним: GET /skills → 200', anon.get('/skills'))
    expect('аноним: GET /llm/status → 200', anon.get('/llm/status'))
    expect('неизвестный метод /api → 404 JSON', anon.get('/no-such-method'), 404)

    # Разделение ролей (SPEC-AUTH-07)
    c = clients
    expect('admin: GET /programs → 403', c['admin'].get('/programs'), 403)
    expect('admin: POST /programs → 403', c['admin'].post('/programs', json={'request': 'Программа по Python, 16 часов'}), 403)
    expect('admin: GET /reviews → 403', c['admin'].get('/reviews'), 403)
    expect('head: POST /programs → 403', c['ahmed'].post('/programs', json={'request': 'Программа по Python, 16 часов'}), 403)
    expect('expert: POST /programs → 403', c['timur'].post('/programs', json={'request': 'Программа по Python, 16 часов'}), 403)
    expect('methodist: GET /admin/users → 403', c['madina'].get('/admin/users'), 403)
    expect('head: GET /admin/settings → 403', c['ahmed'].get('/admin/settings'), 403)
    expect('expert: GET /kb/documents → 403', c['timur'].get('/kb/documents'), 403)
    expect('expert: GET /org/profile → 403', c['timur'].get('/org/profile'), 403)
    expect('api: POST /kb/documents → 403', c['api'].post('/kb/documents', files={'file': ('a.txt', b'x' * 10)}), 403)
    expect('methodist: GET /reviews → 403', c['madina'].get('/reviews'), 403)
    for user in ('madina', 'timur', 'ahmed', 'admin'):
        t = expect(f'{user}: GET /me/tasks', c[user].get('/me/tasks'))
        if t:
            R.check(f'{user}: задачи по ролям methodist/expert/head', {'methodist', 'expert', 'head'} <= set(t.get('tasks', {})), t)
    return clients


# --------------------------------------------------------------------------- 2. методист
def _answers_for(case: dict[str, Any], questions: list[dict[str, Any]]) -> dict[str, str]:
    """Ответы методиста: известные из кейса — по полю, первый оставшийся — «На ваше усмотрение», прочие — первый вариант."""
    out: dict[str, str] = {}
    discretion_used = False
    for q in questions:
        if q['field'] in case.get('answers', {}):
            out[q['id']] = case['answers'][q['field']]
        elif not discretion_used:
            out[q['id']] = 'На ваше усмотрение'
            discretion_used = True
        else:
            out[q['id']] = (q.get('options') or ['На ваше усмотрение'])[0]
    if questions and not discretion_used:
        # хотя бы один ответ «На ваше усмотрение» — последний вопрос
        out[questions[-1]['id']] = 'На ваше усмотрение'
    return out


def methodist_build(clients: dict[str, Client], case: dict[str, Any]) -> dict[str, Any] | None:
    R.head(f'Методист: создание программы (кейс {case["id"]})')
    m = clients['madina']
    created = expect('POST /programs (interactive)', m.post('/programs', json={'request': case['request'], 'attachments': attachments(case)}))
    if not created:
        return None
    pid = created['program_id']
    prog = created.get('program') or {}
    if created['status'] == 'questions':
        qs = created.get('questions') or []
        R.check('вопросов не больше 5', 0 < len(qs) <= 5, len(qs))
        R.check('у каждого вопроса есть варианты', all(q.get('options') for q in qs), qs)
        ans = _answers_for(case, qs)
        r = expect('POST /answers → 202', m.post(f'/programs/{pid}/answers', json={'answers': ans}), 202)
        if not r:
            return None
        info = wait_job(m, r['job_id'])
        R.check('задание каркаса завершено', info.get('status') == 'done', info)
        prog = expect('GET /programs/{id} после ответов', m.get(f'/programs/{pid}')) or {}
        discretion = [a for a in prog.get('assumptions', []) if 'усмотрени' in a.get('source', '')]
        R.check('ответ «На ваше усмотрение» стал допущением из профиля', bool(discretion), prog.get('assumptions'))
        expect('повторные ответы → 409', m.post(f'/programs/{pid}/answers', json={'answers': ans}), 409)
    else:
        R.check('статус после создания — skeleton', created['status'] == 'skeleton', created['status'])
        prog = expect('GET /programs/{id} после создания', m.get(f'/programs/{pid}')) or {}
    R.check('каркас собран (статус skeleton)', prog.get('status') == 'skeleton', prog.get('status'))
    mods = prog.get('modules') or []
    R.check('в каркасе есть модули и темы', bool(mods) and all(x['topics'] for x in mods), len(mods))
    vol = VOLUME_BY_CASE[case['id']]
    tot = prog.get('totals') or {}
    final_h = (prog.get('final_assessment') or {}).get('hours', 0)
    R.check(f'сумма часов каркаса = {vol}', tot.get('total', -1) + final_h == vol, (tot, final_h))
    title = prog.get('title') or ''
    R.check('название программы цело (не пустое, кавычки «» парные)', len(title) > 3 and title.count('«') == title.count('»'), title)
    if case['id'] == 4:
        text = ' '.join(x['title'] + ' ' + ' '.join(t['title'] for t in x['topics']) for x in mods).lower()
        R.check('каркас кейса 4 — по кибербезопасности', 'безопасн' in text or 'кибер' in text, [x['title'] for x in mods])
    return {'pid': pid, 'program': prog}


def _topic_with_room(mods: list[dict[str, Any]], kind: str = 'lk') -> tuple[dict, dict, dict] | None:
    for mod in mods:
        ts = mod['topics']
        for a in ts:
            for b in ts:
                if a['id'] != b['id'] and a['hours'][kind] >= 1:
                    return mod, a, b
    return None


def methodist_upload(clients: dict[str, Client]) -> None:
    """Создание из интерфейса: multipart с текстом и файлом-образцом (POST /programs/upload)."""
    R.head('Методист: создание через форму с файлом')
    m = clients['madina']
    case = load_cases()[4]
    sample = ROOT / case['attachments'][0]
    r = expect('POST /programs/upload (текст + .docx)', m.post('/programs/upload', data={'text': case['request'], 'norm_mode': 'gos'},
                                                              files={'files': (sample.name, sample.read_bytes(), 'application/octet-stream')}))
    if not r:
        return
    refs = (r.get('program') or {}).get('references') or []
    R.check('файл-образец разобран', any(x.get('name') == sample.name and x.get('chars', 0) > 100 for x in refs), [x.get('name') for x in refs])
    if r.get('job_id'):
        info = wait_job(m, r['job_id'])
        R.check('каркас из формы собран', info.get('status') == 'done', info)
    doc = m.get(f'/programs/{r["program_id"]}').json()
    R.check('после формы — вопросы или каркас', doc['status'] in ('questions', 'skeleton'), doc['status'])
    big = m.post('/programs/upload', data={'text': 'Программа по Python'}, files=[('files', (f'f{i}.txt', b'x' * 20)) for i in range(6)])
    expect('больше 5 файлов → 400', big, 400)


def methodist_skeleton(clients: dict[str, Client], state: dict[str, Any]) -> bool:
    R.head('Методист: каркас, проверки, решения «!», утверждение')
    m = clients['madina']
    pid = state['pid']
    rep = expect('GET /report (каркас)', m.get(f'/programs/{pid}/report'))
    if rep is not None:
        R.check('отчёт содержит правила и стадию skeleton', rep.get('stage') == 'skeleton' and bool(rep.get('rules')), rep.get('stage'))
    prog = expect('GET /programs/{id}', m.get(f'/programs/{pid}')) or {}
    mods = prog.get('modules') or []
    vol_before = prog['totals']['total']

    # правка часов темы внутри модуля: итог модуля и программы сохраняется
    pick = None
    for kind in ('lk', 'pr', 'srs', 'lb'):
        pick = _topic_with_room(mods, kind)
        if pick:
            break
    if pick:
        mod, a, b = pick
        patch = {'modules': [{'id': mod['id'], 'topics': [
            {'id': a['id'], 'hours': {kind: a['hours'][kind] - 1}},
            {'id': b['id'], 'hours': {kind: b['hours'][kind] + 1}},
        ]}]}
        r = expect('PATCH /skeleton: перенос 1 ч между темами', m.patch(f'/programs/{pid}/skeleton', json=patch))
        if r:
            newmod = next(x for x in r['program']['modules'] if x['id'] == mod['id'])
            na = next(t for t in newmod['topics'] if t['id'] == a['id'])
            R.check('часы темы изменены', na['hours'][kind] == a['hours'][kind] - 1, na['hours'])
            R.check('итог модуля сохранён', newmod['hours']['total'] == mod['hours']['total'], (newmod['hours'], mod['hours']))
            R.check('итог программы сохранён', r['totals']['total'] == vol_before, r['totals'])
            R.check('каждая тема: ЛК+ПР+ЛБ+СРС = всего', all(t['hours']['total'] == sum(t['hours'][k] for k in ('lk', 'pr', 'lb', 'srs'))
                                                         for mm in r['program']['modules'] for t in mm['topics']))
    # переименование модуля
    if mods:
        r = expect('PATCH /skeleton: название модуля', m.patch(f'/programs/{pid}/skeleton', json={'modules': [{'id': mods[0]['id'], 'title': mods[0]['title'] + ' (ред.)'}]}))
        if r:
            R.check('название модуля сохранено', r['program']['modules'][0]['title'].endswith('(ред.)'))
    # перестановка тем (решение V-21 «принять» с узлом a>b): темы меняются местами, часы позиций остаются
    prog = m.get(f'/programs/{pid}').json()
    mod2 = next((x for x in prog['modules'] if len(x['topics']) >= 2), None)
    if mod2:
        t1, t2 = mod2['topics'][0], mod2['topics'][1]
        r = expect('перестановка тем (V-21 accept a>b)', m.post(f'/programs/{pid}/skeleton/decisions', json={'rule_id': 'V-21', 'decision': 'accept', 'node': f'{t1["id"]}>{t2["id"]}'}))
        if r:
            nm = next(x for x in r['program']['modules'] if x['id'] == mod2['id'])
            R.check('темы поменялись местами', nm['topics'][0]['title'] == t2['title'] and nm['topics'][1]['title'] == t1['title'], [t['title'] for t in nm['topics'][:2]])
            R.check('часы модуля после перестановки не изменились', nm['hours'] == mod2['hours'])
    # решения по пунктам «!»
    rep = m.get(f'/programs/{pid}/report').json()
    pending = [p for p in rep.get('proposals', []) if not p.get('decided')]
    seen: set[tuple[str, str]] = set()
    first = True
    for p in pending:
        key = (p['rule_id'], p.get('node', ''))
        if key in seen:
            continue
        seen.add(key)
        decision = 'keep' if first and p['rule_id'] != 'V-10' else 'accept'
        first = False
        expect(f'решение {decision} по «!» {p["rule_id"]} {p.get("node", "")}'.strip(), m.post(f'/programs/{pid}/skeleton/decisions', json={
            'rule_id': p['rule_id'], 'decision': decision, 'node': p.get('node', ''), 'proposal': p.get('proposal', ''), 'option_id': p.get('option_id', '')}))
    rep = m.get(f'/programs/{pid}/report').json()
    left = [p for p in rep.get('proposals', []) if not p.get('decided')]
    R.check('после решений не осталось нерешённых «!»', not left, left[:3])
    fails = [r_['id'] for r_ in rep.get('rules', []) if r_['status'] == 'fail']
    R.check('в каркасе нет ошибок ✕', not fails, fails)
    expect('head не утверждает каркас → 403', clients['ahmed'].post(f'/programs/{pid}/skeleton/approve', json={'decision': 'approve'}), 403)
    r = expect('POST /skeleton/approve → 202', m.post(f'/programs/{pid}/skeleton/approve', json={'decision': 'approve'}), 202)
    if not r:
        return False
    info = wait_job(m, r['job_id'])
    R.check('генерация комплекта завершена', info.get('status') == 'done', info)
    prog = m.get(f'/programs/{pid}').json()
    R.check('статус kit_ready', prog['status'] == 'kit_ready', prog['status'])
    kit = prog.get('kit') or {}
    R.check('в комплекте есть вопросы, задания, лекции, рабочие программы',
            all(kit.get(k) for k in ('questions', 'tasks', 'lectures', 'module_programs')), {k: len(kit.get(k) or []) for k in ('questions', 'tasks', 'lectures', 'module_programs')})
    rep = prog.get('report') or {}
    R.check('блокирующие проверки 10/10', rep.get('blocking_passed') == rep.get('blocking_total') == 10, (rep.get('blocking_passed'), rep.get('blocking_total')))
    expect('PATCH /skeleton после утверждения → 409', m.patch(f'/programs/{pid}/skeleton', json={'goal': 'x'}), 409)
    return True


def methodist_kit_tools(clients: dict[str, Client], state: dict[str, Any], case: dict[str, Any]) -> None:
    R.head('Методист: правки, версии, откат, шаблон, адаптация, актуализация, песочница')
    m = clients['madina']
    pid = state['pid']
    prog = m.get(f'/programs/{pid}').json()
    topic = prog['modules'][0]['topics'][0]
    # точечная правка: dry-run показывает план и «было/станет»
    dry = expect('POST /edits dry_run (тема)', m.post(f'/programs/{pid}/edits', json={'target': topic['id'], 'new_title': topic['title'] + ' и практика', 'dry_run': True}))
    if dry:
        R.check('dry_run: план потомков и превью', dry.get('applied') is False and dry.get('plan', {}).get('nodes') and dry.get('preview', {}).get('before') == topic['title'], dry.get('preview'))
    v_before = m.get(f'/programs/{pid}').json()['version']
    q = prog['kit']['questions'][0]
    ed = expect('POST /edits: правка вопроса', m.post(f'/programs/{pid}/edits', json={'target': q['id'], 'instruction': 'Сделай вопрос сложнее и практичнее'}))
    if ed:
        R.check('правка применена и проверена', ed.get('applied') and ed.get('check_ok'), {k: ed.get(k) for k in ('applied', 'check_ok', 'changed')})
        R.check('правка затронула только потомков', set(ed.get('changed') or []) <= set(ed['plan']['nodes']) | {x for x in ed.get('changed', []) if x.endswith(':hours')}, ed.get('changed'))
    # правка часов темы после сборки: итог модуля сохраняется
    mod = prog['modules'][0]
    pick = None
    for kind in ('pr', 'lk', 'srs', 'lb'):
        tps = [t for t in mod['topics'] if t['hours'][kind] >= 1]
        if len(mod['topics']) >= 2 and tps:
            pick = (kind, tps[-1])
            break
    if pick:
        kind, t = pick
        r = expect('POST /edits hours:<тема>', m.post(f'/programs/{pid}/edits', json={'target': f'hours:{t["id"]}', 'hours': {kind: t['hours'][kind] - 1}}))
        if r:
            nm = next(x for x in r['program']['modules'] if x['id'] == mod['id'])
            nt = next(x for x in nm['topics'] if x['id'] == t['id'])
            R.check('часы темы изменены, итог модуля прежний', nt['hours'][kind] == t['hours'][kind] - 1 and nm['hours']['total'] == mod['hours']['total'], (nt['hours'], nm['hours']))
    expect('POST /edits без цели и описания → 409', m.post(f'/programs/{pid}/edits', json={'target': '', 'instruction': ''}), 409)
    # версии, сравнение, откат («отменить» последнюю правку)
    vers = expect('GET /versions', m.get(f'/programs/{pid}/versions')) or []
    R.check('версий не меньше 3', len(vers) >= 3, len(vers))
    if len(vers) >= 2:
        a, b = vers[1]['version'], vers[0]['version']
        d = expect(f'GET /versions/{a}/diff/{b}', m.get(f'/programs/{pid}/versions/{a}/diff/{b}'))
        R.check('сравнение версий возвращает объект', isinstance(d, dict), d)
        expect('GET /versions/999/diff → 404', m.get(f'/programs/{pid}/versions/999/diff/{b}'), 404)
    cur = m.get(f'/programs/{pid}').json()
    r = expect(f'откат к версии {v_before} (отмена правки)', m.post(f'/programs/{pid}/versions/{v_before}/restore'))
    if r:
        after = m.get(f'/programs/{pid}').json()
        q_after = next(x for x in after['kit']['questions'] if x['id'] == q['id'])
        R.check('вопрос вернулся к тексту до правки', q_after['stem'] == q['stem'], (q_after['stem'][:80], q['stem'][:80]))
        R.check('версия после отката — новая', after['version'] > cur['version'], (after['version'], cur['version']))
        R.check('статус после отката kit_ready', after['status'] == 'kit_ready', after['status'])
    expect('откат к несуществующей версии → 404', m.post(f'/programs/{pid}/versions/999/restore'), 404)
    expect('GET /sections', m.get(f'/programs/{pid}/sections'))
    # шаблон: после утверждения каркаса смена запрещена (FR-06)
    expect('смена шаблона после утверждения → 409', m.post(f'/programs/{pid}/template', json={'program_type': 'doop'}), (409, 400))
    # адаптация → новая программа; на ней смена шаблона до утверждения каркаса
    ad = expect('POST /adapt (новый объём и аудитория)', m.post(f'/programs/{pid}/adapt', json={'volume_h': 36, 'audience': 'Методисты колледжей'}))
    if ad:
        R.check('адаптация создала новую программу', ad['program_id'] != pid)
        aprog = ad['program']
        R.check('адаптированная программа 36 ч', aprog['volume_h'] == 36, aprog['volume_h'])
        R.check('адаптированная программа — каркас', aprog['status'] in ('skeleton', 'returned'), aprog['status'])
        new_type = 'dpp_pk_internship' if aprog.get('type') != 'dpp_pk_internship' else 'dpp_pk'
        t = expect(f'смена шаблона на {new_type} (до утверждения каркаса)', m.post(f'/programs/{ad["program_id"]}/template', json={'program_type': new_type}))
        if t:
            R.check('тип программы сменился', t['program']['type'] == new_type, t['program']['type'])
            final_h = t['program']['final_assessment']['hours']
            R.check('часы после смены шаблона сходятся с объёмом', sum(x['hours']['total'] for x in t['program']['modules']) + final_h == t['program']['volume_h'])
        expect('неизвестный шаблон → 400', m.post(f'/programs/{ad["program_id"]}/template', json={'program_type': 'nope'}), (400, 422))
        state['adapted'] = ad['program_id']
    expect('api не адаптирует чужую программу → 403', clients['api'].post(f'/programs/{pid}/adapt', json={'volume_h': 36}), 403)
    act = expect('GET /actualize', m.get(f'/programs/{pid}/actualize'))
    if act:
        R.check('актуализация: поля findings/total', 'findings' in act and act['total'] == len(act['findings']))
    sample = ROOT / 'data' / 'samples' / 'stazh_biznes_analiz_248.docx'
    if sample.exists():
        af = expect('POST /actualize (файл .docx)', m.post('/actualize', files={'file': (sample.name, sample.read_bytes(), 'application/octet-stream')}))
        if af:
            R.check('актуализация файла прочитала текст', af.get('chars', 0) > 100, af.get('chars'))
    sb = expect('GET /sandbox', m.get(f'/programs/{pid}/sandbox'))
    if sb is not None:
        R.check('песочница отвечает отчётом', isinstance(sb, dict), sb)


def assign_experts(clients: dict[str, Client], state: dict[str, Any]) -> None:
    R.head('Методист: назначение экспертов')
    m = clients['madina']
    pid = state['pid']
    sug = expect('GET /experts (подсказки)', m.get(f'/programs/{pid}/experts'))
    _ = sug
    prog = m.get(f'/programs/{pid}').json()
    mods = prog['modules']
    plan = {}
    for i, mod in enumerate(mods):
        plan[mod['id']] = 'u-timur' if i % 2 == 0 else 'u-olga'
    if len(mods) == 1:
        R.check('в программе больше одного модуля для двух экспертов', False, 'один модуль: olga не получит модуль')
    expect('назначение несуществующего эксперта → 400', m.put(f'/programs/{pid}/modules/{mods[0]["id"]}/expert', json={'expert_id': 'u-ahmed'}), 400)
    for mid, ex in plan.items():
        expect(f'назначить {ex} на {mid}', m.put(f'/programs/{pid}/modules/{mid}/expert', json={'expert_id': ex}))
    prog = m.get(f'/programs/{pid}').json()
    R.check('статус on_review', prog['status'] == 'on_review', prog['status'])
    state['plan'] = plan


def expert_review(clients: dict[str, Client], state: dict[str, Any], user: str) -> None:
    uid = f'u-{user}'
    R.head(f'Эксперт {user}: вычитка своих модулей')
    e = clients[user]
    pid = state['pid']
    mine = {mid for mid, ex in state['plan'].items() if ex == uid}
    others = set(state['plan']) - mine
    notes = expect('GET /notifications', e.get('/notifications')) or []
    R.check('уведомление о назначении', any(n.get('program_id') == pid for n in notes), len(notes))
    rv = expect('GET /reviews', e.get('/reviews')) or []
    my_tasks = [x for x in rv if x['program_id'] == pid]
    R.check('в заданиях только свои модули', {x['module_id'] for x in my_tasks} == mine, ({x['module_id'] for x in my_tasks}, mine))
    lst = expect('GET /programs (эксперт)', e.get('/programs')) or []
    R.check('программа есть в списке эксперта', any(x['id'] == pid for x in lst))
    doc = expect('GET /programs/{id} (эксперт)', e.get(f'/programs/{pid}')) or {}
    R.check('эксперт видит только свои модули', {x['id'] for x in doc.get('modules', [])} == mine, [x['id'] for x in doc.get('modules', [])])
    kit = doc.get('kit') or {}
    R.check('вопросы и лекции только своих модулей', all(x.get('module_id') in mine for k in ('questions', 'lectures', 'tasks') for x in kit.get(k, [])))
    R.check('полный комплект program скрыт', doc.get('program') is None)
    expect('эксперт: выгрузка → 403', e.get(f'/programs/{pid}/export/docx'), 403)
    expect('эксперт: журнал → 403', e.get(f'/programs/{pid}/events'), 403)
    expect('эксперт: версии → 403', e.get(f'/programs/{pid}/versions'), 403)
    if others:
        other = sorted(others)[0]
        expect('комментарий к чужому модулю → 403', e.post(f'/programs/{pid}/comments', json={'module_id': other, 'text': 'Чужой модуль'}), 403)
        expect('решение по чужому модулю → 403', e.post(f'/programs/{pid}/reviews/decision', json={'module_id': other, 'decision': 'accept', 'score': 5}), 403)
    full = clients['madina'].get(f'/programs/{pid}').json()
    for task in my_tasks:
        mid = task['module_id']
        rid = task['rid']
        topic = next(x for x in full['modules'] if x['id'] == mid)['topics'][0]
        expect('эксперт не правит часы → 403', e.post(f'/programs/{pid}/edits', json={'target': f'hours:{topic["id"]}', 'hours': {'lk': 1}}), 403)
        c = expect(f'комментарий к модулю {mid} (по rid)', e.post(f'/reviews/{rid}/comments', json={'text': 'Добавьте пример из практики школы', 'node_id': topic['id']}))
        if c:
            ans = expect('методист отвечает на комментарий', clients['madina'].post(f'/programs/{pid}/comments/answer', json={'comment_id': c['comment']['id'], 'answer': 'Добавим в следующей версии'}))
            if ans:
                R.check('комментарий отвечен', ans['comment']['status'] == 'answered', ans['comment']['status'])
        if task is my_tasks[0]:
            # FR-48: эксперт просит агента предложить правку и сам её подтверждает
            pa = expect('комментарий с запросом правки агенту', e.post(f'/reviews/{rid}/comments', json={'text': 'Сделайте формулировку темы конкретнее', 'node_id': topic['id'], 'ask_agent': True}))
            if pa:
                R.check('предложение агента ждёт подтверждения эксперта', pa['comment']['status'] == 'proposed' and bool(pa['comment']['agent_proposal']), pa['comment'].get('status'))
                ap = expect('эксперт подтверждает правку агента', e.post(f'/programs/{pid}/comments/answer', json={'comment_id': pa['comment']['id'], 'apply_proposal': True}))
                if ap:
                    R.check('правка агента применена', ap['comment']['status'] == 'applied', ap['comment']['status'])
        early = e.post(f'/reviews/{rid}/decision', json={'decision': 'accept', 'score': 5})
        expect('принять модуль до проверки элементов → 409', early, 409)
        doc = e.get(f'/programs/{pid}').json()
        k = doc['kit']
        items = ([f'mp-{mid}'] if any(x['module_id'] == mid for x in k.get('module_programs', [])) else []) + \
            [x['id'] for key in ('lectures', 'questions', 'tasks') for x in k.get(key, []) if x.get('module_id') == mid]
        ok = True
        for it in items:
            r = e.post(f'/reviews/{rid}/decision', json={'decision': 'accept_item', 'node_id': it})
            ok &= r.status_code == 200
        R.check(f'приняты все элементы модуля {mid} ({len(items)})', ok and bool(items))
        rv = {x['rid']: x for x in e.get('/reviews').json()}
        R.check('items_done = items_total', rv[rid]['items_done'] == rv[rid]['items_total'], rv[rid])
        r = expect(f'принять модуль {mid} с оценкой 5', e.post(f'/reviews/{rid}/decision', json={'decision': 'accept', 'score': 5}))
        if r:
            st = next(x for x in clients['madina'].get(f'/programs/{pid}').json()['modules'] if x['id'] == mid)['review_status']
            R.check('модуль принят', st == 'accepted', st)


def approval_flow(clients: dict[str, Client], state: dict[str, Any]) -> None:
    R.head('Согласование: методист → руководитель')
    m, h = clients['madina'], clients['ahmed']
    pid = state['pid']
    expect('эксперт не отправляет на утверждение → 403', clients['timur'].post(f'/programs/{pid}/submit'), 403)
    r = expect('POST /submit', m.post(f'/programs/{pid}/submit'))
    if r:
        R.check('статус on_approval', r['status'] == 'on_approval', r)
    notes = h.get('/notifications').json()
    R.check('руководитель получил уведомление', any(n['program_id'] == pid for n in notes))
    lst = expect('head: GET /programs?status=on_approval', h.get('/programs', params={'status': 'on_approval,approved'})) or []
    R.check('программа в фильтре руководителя', any(x['id'] == pid for x in lst))
    doc = expect('head: GET /programs/{id}', h.get(f'/programs/{pid}')) or {}
    q = doc.get('quality') or {}
    R.check('руководитель видит качество и затраты', 'generation_rub' in q and 'human_decisions' in q, list(q))
    R.check('готовность 100 %', (doc.get('readiness') or {}).get('index') == 100, doc.get('readiness'))
    ev = expect('head: GET /events', h.get(f'/programs/{pid}/events')) or []
    R.check('журнал содержит ключевые события', {'created', 'skeleton_approved', 'kit_ready', 'assign', 'submitted'} <= {x.get('action') for x in ev},
            sorted({x.get('action') for x in ev}))
    expect('head: GET /report', h.get(f'/programs/{pid}/report'))
    expect('head: GET /versions', h.get(f'/programs/{pid}/versions'))
    expect('методист не утверждает программу → 403', m.post(f'/programs/{pid}/approval', json={'decision': 'approve'}), 403)
    expect('возврат без комментария → 409', h.post(f'/programs/{pid}/approval', json={'decision': 'return'}), 409)
    r = expect('head возвращает с комментарием', h.post(f'/programs/{pid}/approval', json={'decision': 'return', 'comment': 'Уточните литературу'}))
    if r:
        R.check('статус returned', r['status'] == 'returned', r)
    notes = m.get('/notifications').json()
    R.check('методист получил возврат с комментарием', any('Уточните литературу' in n.get('text', '') for n in notes))
    r = expect('повторная отправка', m.post(f'/programs/{pid}/submit'))
    r = expect('head утверждает', h.post(f'/programs/{pid}/approval', json={'decision': 'approve'}))
    if r:
        R.check('статус approved', r['status'] == 'approved', r)
        ev = h.get(f'/programs/{pid}/events').json()
        R.check('журнал: утверждение записано словами', ev[0]['action'] == 'approved' and ev[0]['text'].startswith('Программа утверждена'), ev[0])
    expect('правка утверждённой программы → 409', m.post(f'/programs/{pid}/edits', json={'target': 'auto', 'instruction': 'Поменяй тему'}), 409)


# --------------------------------------------------------------------------- 3. выгрузки
def _docx_text(content: bytes) -> str:
    import docx  # python-docx

    d = docx.Document(io.BytesIO(content))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return '\n'.join(parts)


def exports(clients: dict[str, Client], state: dict[str, Any]) -> None:
    R.head('Выгрузки всех форматов')
    h = clients['ahmed']
    pid = state['pid']
    prog = h.get(f'/programs/{pid}').json()
    title = prog['title']
    got: dict[str, bytes] = {}
    for fmt in ('docx', 'lectures_docx', 'order_draft', 'pptx', 'gift', 'moodle_xml', 'json'):
        r = h.get(f'/programs/{pid}/export/{fmt}')
        if R.check(f'GET /export/{fmt} → 200', r.status_code == 200 and len(r.content) > 50, f'HTTP {r.status_code}'):
            got[fmt] = r.content
            R.check(f'{fmt}: Content-Disposition attachment', 'attachment' in r.headers.get('content-disposition', ''))
    expect('неизвестный формат → 400', h.get(f'/programs/{pid}/export/pdfx'), 400)
    expect('admin: выгрузка → 403', clients['admin'].get(f'/programs/{pid}/export/docx'), 403)
    if 'docx' in got:
        try:
            text = _docx_text(got['docx'])
            R.check('DOCX открывается python-docx', True)
            R.check('DOCX: название программы', title[:30] in text, title)
            R.check('DOCX: учебный план с модулями', all(x['title'][:20] in text for x in prog['modules']))
            R.check('DOCX: пустые поля утверждения ____', '____' in text)
        except Exception as exc:  # noqa: BLE001
            R.check('DOCX открывается python-docx', False, exc)
    if 'lectures_docx' in got:
        try:
            text = _docx_text(got['lectures_docx'])
            R.check('лекции DOCX открываются', len(text) > 200, len(text))
            R.check('лекции DOCX: есть заголовки лекций', any(lec['title'][:20] in text for lec in prog['kit']['lectures']))
        except Exception as exc:  # noqa: BLE001
            R.check('лекции DOCX открываются', False, exc)
    if 'order_draft' in got:
        try:
            text = _docx_text(got['order_draft'])
            R.check('приказ DOCX открывается', 'ПРИКАЗ' in text)
            R.check('приказ: номер, ответственный и подпись — пустые поля', text.count(BLANK) >= 4, text.count(BLANK))
            R.check('приказ: дата не заполнена', '«__» ________ 20__' in text)
            R.check(f'приказ: объём {prog["volume_h"]} ак. ч', f'{prog["volume_h"]} ак. ч' in text)
        except Exception as exc:  # noqa: BLE001
            R.check('приказ DOCX открывается', False, exc)
    if 'pptx' in got:
        try:
            import pptx

            p = pptx.Presentation(io.BytesIO(got['pptx']))
            n_slides = sum(len(lec.get('slides') or []) for lec in prog['kit']['lectures'])
            R.check('PPTX открывается python-pptx', len(p.slides) >= 1)
            R.check('PPTX: титул + слайды лекций', len(p.slides) == 1 + n_slides or (n_slides == 0 and len(p.slides) == 2), (len(p.slides), n_slides))
            R.check('PPTX: название на титуле', p.slides[0].shapes.title.text == title)
        except Exception as exc:  # noqa: BLE001
            R.check('PPTX открывается python-pptx', False, exc)
    if 'moodle_xml' in got:
        try:
            root = ET.fromstring(got['moodle_xml'])
            qs = root.findall("question[@type='multichoice']")
            R.check('Moodle XML разбирается', root.tag == 'quiz')
            R.check('Moodle XML: все вопросы комплекта', len(qs) == len([q for q in prog['kit']['questions'] if q.get('assessment_id')]), (len(qs), len(prog['kit']['questions'])))
            R.check('Moodle XML: ровно один верный ответ в каждом', all(sum(1 for a in q.findall('answer') if a.get('fraction') == '100') == 1 for q in qs))
        except ET.ParseError as exc:
            R.check('Moodle XML разбирается', False, exc)
    if 'gift' in got:
        g = got['gift'].decode('utf-8')
        R.check('GIFT: категории и вопросы', '$CATEGORY:' in g and g.count('::') >= 2 * min(1, len(prog['kit']['questions'])))
        R.check('GIFT: у каждого вопроса один «=»', all(line.count(' =') + line.count('{ =') >= 1 for line in g.splitlines() if line.startswith('::')))
    if 'json' in got:
        try:
            j = json.loads(got['json'])
            p = j.get('program') or {}
            need = {'id', 'type', 'template', 'issued_document', 'title', 'volume_h', 'audience', 'form', 'calendar', 'goal', 'final_assessment',
                    'competencies', 'modules', 'assessments', 'questions', 'tasks', 'lectures', 'module_programs', 'sources', 'approvals'}
            R.check('JSON 4.8: поля program', need <= set(p), sorted(need - set(p)))
            R.check('JSON 4.8: нет служебных usage/params', 'usage' not in p and 'params' not in p)
            R.check('JSON 4.8: часы модулей total/lk/pr/lb/srs', all({'total', 'lk', 'pr', 'lb', 'srs'} <= set(mm['hours']) for mm in p.get('modules', [])))
            R.check('JSON 4.8: компетенции с индикаторами и РО', all(c.get('indicators') is not None for c in p.get('competencies', [])) and bool(p.get('competencies')),
                    [list(c) for c in p.get('competencies', [])[:1]])
            R.check('JSON 4.8: статус approved', p.get('status') == 'approved', p.get('status'))
            vol = sum(mm['hours']['total'] for mm in p['modules']) + p['final_assessment'].get('hours', 0)
            R.check('JSON 4.8: сумма часов = объём', vol == p['volume_h'], (vol, p['volume_h']))
        except ValueError as exc:
            R.check('JSON разбирается', False, exc)


# --------------------------------------------------------------------------- 4. администратор
def admin_flow(clients: dict[str, Client], http: httpx.Client) -> None:
    R.head('Администратор: пользователи, настройки, навыки, база знаний, журнал')
    a = clients['admin']
    users = expect('GET /admin/users', a.get('/admin/users')) or []
    R.check('в списке 6 демо-учёток', {'madina', 'timur', 'olga', 'ahmed', 'admin', 'api'} <= {u['login'] for u in users})
    login_ = 'e2e' + uuid.uuid4().hex[:6]
    u = expect('POST /admin/users', a.post('/admin/users', json={'login': login_, 'name': 'Проверка Регресса', 'password': 'Passw0rd!x', 'roles': ['expert']}), 201)
    if u:
        r = http.post(f'{API}/auth/login', json={'login': login_, 'password': 'Passw0rd!x'})
        R.check('новый пользователь входит', r.status_code == 200 and r.json()['user']['role'] == 'expert', r.status_code)
        p = expect('PATCH роли → methodist, expert', a.patch(f'/admin/users/{u["id"]}', json={'roles': ['methodist', 'expert']}))
        if p:
            R.check('роли обновлены', p['roles'] == ['methodist', 'expert'], p['roles'])
        r = http.post(f'{API}/auth/login', json={'login': login_, 'password': 'Passw0rd!x', 'role': 'methodist'})
        R.check('вход новой ролью methodist', r.status_code == 200)
        tok = r.json().get('access_token') if r.status_code == 200 else None
        expect('PATCH active=false', a.patch(f'/admin/users/{u["id"]}', json={'active': False}))
        r = http.post(f'{API}/auth/login', json={'login': login_, 'password': 'Passw0rd!x'})
        R.check('отключённый не входит (401)', r.status_code == 401, r.status_code)
        if tok:
            R.check('токен отключённого недействителен (401)', Client(http, tok).get('/auth/me').status_code == 401)
    expect('дубль логина → 409', a.post('/admin/users', json={'login': 'madina', 'name': 'Дубль', 'password': 'Passw0rd!x', 'roles': ['expert']}), 409)
    expect('слабый пароль → 400', a.post('/admin/users', json={'login': login_ + 'w', 'name': 'Слабый', 'password': 'aaaaaaaa', 'roles': ['expert']}), 400)
    expect('нельзя снять роль у последнего admin → 409', a.patch('/admin/users/u-admin', json={'roles': ['methodist']}), 409)
    st = expect('GET /admin/settings', a.get('/admin/settings'))
    if st:
        secrets = [f for f in st['fields'] if f['type'] == 'secret']
        R.check('секреты в настройках есть и замаскированы', bool(secrets) and all(not f['value'] or str(f['value']).startswith('••••') for f in secrets),
                [(f['key'], bool(f['value'])) for f in secrets])
    secret = 'smtp-' + uuid.uuid4().hex
    r = expect('PUT /admin/settings: секрет smtp_password', a.put('/admin/settings', json={'values': {'smtp_password': secret}}))
    if r:
        f = next(x for x in r['fields'] if x['key'] == 'smtp_password')
        R.check('секрет отдаётся маской ••••+4', f['value'] == '••••' + secret[-4:] and secret not in json.dumps(r), f['value'][:6])
        again = a.get('/admin/settings').text
        R.check('GET /admin/settings не содержит секрета', secret not in again)
        r2 = a.put('/admin/settings', json={'values': {'smtp_password': f['value']}})
        R.check('маска не перезаписывает секрет', r2.status_code == 200 and 'smtp_password' not in r2.json().get('changed', []), r2.text[:200])
        expect('PUT /admin/settings clear', a.put('/admin/settings', json={'clear': ['smtp_password']}))
    expect('неизвестная настройка → 400', a.put('/admin/settings', json={'values': {'nope': 1}}), 400)
    sk = expect('GET /admin/skills', a.get('/admin/skills')) or []
    R.check('навыки с параметрами', bool(sk) and all('temperature' in s for s in sk), len(sk))
    if sk:
        name = sk[0]['name']
        r = expect(f'PUT /admin/skills/{name} temperature=0.3', a.put(f'/admin/skills/{name}', json={'temperature': 0.3}))
        if r:
            R.check('параметр навыка сохранён', abs(r['temperature'] - 0.3) < 1e-9 and 'temperature' in r['overridden'], r.get('overridden'))
        expect('параметр вне диапазона → 400', a.put(f'/admin/skills/{name}', json={'temperature': 50}), 400)
        r = expect('сброс навыка к SKILL.md', a.put(f'/admin/skills/{name}', json={'reset': True}))
        if r:
            R.check('после сброса нет переопределений', r['overridden'] == [], r['overridden'])
    marker = 'регрессзнание' + uuid.uuid4().hex[:6]
    up = expect('POST /kb/documents (txt)', a.post('/kb/documents', files={'file': ('e2e-polozhenie.txt', f'Положение о стажировке. Ключ {marker}. Итоговая аттестация — защита отчёта.'.encode(), 'text/plain')},
                                                  data={'kind': 'regulation'}))
    if up:
        docs = expect('GET /kb/documents', a.get('/kb/documents')) or []
        R.check('документ в базе знаний', any(d.get('id') == up.get('id') for d in docs), up)
        hits = expect('POST /kb/search', a.post('/kb/search', json={'query': f'стажировка {marker}', 'k': 5})) or []
        R.check('поиск находит загруженный документ', any(marker in json.dumps(h_, ensure_ascii=False) or h_.get('doc_id') == up.get('id') or h_.get('id') == up.get('id') for h_ in hits),
                [h_.get('title') or h_.get('name') for h_ in hits])
        ex = expect('эксперт ищет в базе знаний', clients['timur'].post('/kb/search', json={'query': 'закон об образовании'}))
        _ = ex
        expect('DELETE /kb/documents/{id}', a.delete(f'/kb/documents/{up["id"]}'))
    expect('GET /kb/norms', a.get('/kb/norms'))
    expect('GET /org/profile', a.get('/org/profile'))
    prof = clients['madina'].get('/org/profile').json()
    R.check('методист не видит smtp профиля', 'smtp' not in prof)
    expect('PUT /org/profile неизвестное поле → 400', a.put('/org/profile', json={'zzz': 1}), 400)
    expect('GET /org/registry?kind=npa', a.get('/org/registry', params={'kind': 'npa'}))
    j = expect('GET /admin/journal', a.get('/admin/journal')) or []
    kinds = {x.get('action') for x in j}
    R.check('журнал: пользователи, настройки, навыки', {'user_create', 'user_update', 'settings', 'skill'} <= kinds, sorted(kinds))
    R.check('журнал не содержит секрета', secret not in json.dumps(j, ensure_ascii=False))


# --------------------------------------------------------------------------- 5. автопрогон
def autorun_case(http: httpx.Client, case: dict[str, Any]) -> None:
    R.head(f'Автопрогон кейса {case["id"]}')
    t0 = time.monotonic()
    r = http.post(f'{API}/programs', params={'mode': 'auto'}, json={'request': case['request'], 'attachments': attachments(case), 'answers': case['answers']},
                  timeout=1800)
    dt = time.monotonic() - t0
    data = expect(f'POST /programs?mode=auto (аноним, {dt:.1f} с)', r)
    if not data:
        return
    R.check('status done', data['status'] == 'done', (data['status'], data['report'].get('failed_rules'), data.get('agent_notes', [])[-2:]))
    sk = data['skeleton']
    tot = sk['totals']
    vol = VOLUME_BY_CASE[case['id']]
    R.check(f'итого {vol} ч', tot['all'] == vol, tot)
    R.check('ЛК+ПР+ЛБ+СРС+ИА = всего', tot['lk'] + tot['pr'] + tot['lb'] + tot['srs'] + tot['ia'] == tot['all'], tot)
    R.check('строки модулей и тем сходятся', all(mm['lk'] + mm['pr'] + mm['lb'] + mm['srs'] == mm['total'] and sum(t['total'] for t in mm['topics']) == mm['total'] for mm in sk['modules']))
    R.check(f'тип программы {TYPE_BY_CASE[case["id"]]}', sk['type'] == TYPE_BY_CASE[case['id']], sk['type'])
    ids = {s['id'] for s in data['kit']['program']['sources']}
    need = MANDATORY_NPA[case['id']]
    R.check(f'обязательные НПА {", ".join(sorted(need))}', need <= ids, sorted(need - ids))
    R.check('блокирующие проверки 10/10', data['report']['blocking_checks'] == '10/10', data['report']['blocking_checks'])
    R.check('ссылки на все 7 форматов', set(data['files']) == {'docx', 'pptx', 'gift', 'moodle_xml', 'json', 'order_draft', 'lectures_docx'}, sorted(data['files']))
    try:
        from autorun import _checks  # чек-лист кейса из scripts/autorun.py

        for name, ok in _checks(case, data):
            R.check(f'чек-лист: {name}', ok)
    except ImportError as exc:
        R.check('чек-лист scripts/autorun.py импортируется', False, exc)
    # результат читается анонимно (свой) и выгружается
    pid = data['program_id']
    expect('аноним читает свой результат', http.get(f'{API}/programs/{pid}'))
    expect('аноним скачивает JSON', http.get(f'{API}/programs/{pid}/export/json'))


def autorun_async(http: httpx.Client, case: dict[str, Any]) -> None:
    R.head('Автопрогон асинхронно (wait=false)')
    r = http.post(f'{API}/programs', params={'mode': 'auto'}, json={'request': case['request'], 'attachments': attachments(case), 'answers': case['answers'], 'wait': False})
    data = expect('POST /programs?mode=auto wait=false → 202', r, 202)
    if not data:
        return
    info = wait_job(Client(http), data['job_id'])
    R.check('задание done с результатом', info.get('status') == 'done' and info.get('result', {}).get('program_id') == data['program_id'], {k: info.get(k) for k in ('status', 'error')})


def check_expert_isolation(clients: dict[str, Client], state: dict[str, Any]) -> None:
    """Эксперт без назначений в программе не видит её содержимого."""
    R.head('Эксперт без назначения')
    pid = state.get('adapted')
    if not pid:
        return
    for user in ('timur', 'olga'):
        e = clients[user]
        expect(f'{user}: карточка чужой программы → 403', e.get(f'/programs/{pid}'), 403)
        expect(f'{user}: разделы чужой программы → 403', e.get(f'/programs/{pid}/sections'), 403)


# --------------------------------------------------------------------------- main
def lifecycle(clients: dict[str, Client], case: dict[str, Any]) -> None:
    state = step(methodist_build, clients, case)
    if not state:
        return
    if not step(methodist_skeleton, clients, state):
        return
    step(methodist_kit_tools, clients, state, case)
    step(assign_experts, clients, state)
    if 'plan' not in state:
        return
    step(check_expert_isolation, clients, state)
    for user in ('timur', 'olga'):
        step(expert_review, clients, state, user)
    step(approval_flow, clients, state)
    step(exports, clients, state)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    ap.add_argument('--case', type=int, choices=range(1, 6), help='кейс для интерактивного сценария и автопрогона')
    ap.add_argument('--all-cases', action='store_true', help='интерактивный сценарий по каждому из 5 кейсов')
    ap.add_argument('--skip-autorun', action='store_true', help='без автопрогона кейсов')
    args = ap.parse_args()
    cases = {c['id']: c for c in load_cases()}
    t0 = time.monotonic()
    with httpx.Client(base_url=args.base, timeout=600) as http:
        try:
            http.get('/health').raise_for_status()
        except httpx.HTTPError as exc:
            print(f'Сервер {args.base} недоступен: {exc}')
            return 2
        clients = step(auth_and_roles, http)
        if clients and len(clients) == len(DEMO):
            interactive = list(cases) if args.all_cases else [args.case or 4]
            for cid in interactive:
                lifecycle(clients, cases[cid])
            step(methodist_upload, clients)
            step(admin_flow, clients, http)
        if not args.skip_autorun:
            for cid in ([args.case] if args.case and not args.all_cases else list(cases)):
                step(autorun_case, http, cases[cid])
            step(autorun_async, http, cases[1])
    total = R.passed + len(R.failed)
    print(f'\n== Итого: {R.passed}/{total} PASS, {len(R.failed)} FAIL, {time.monotonic() - t0:.0f} с')
    for f in R.failed:
        print(f'  FAIL {f}')
    return 1 if R.failed else 0


if __name__ == '__main__':
    sys.exit(main())
