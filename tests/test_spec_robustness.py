"""Устойчивость конвейера: параллельная генерация без гонок, отказы навыков, шаг clarify, слайды без модели, таймауты LLM."""

from __future__ import annotations

import asyncio
import io
import json
import os
import random
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.llm import client as c  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = {x['id']: x for x in json.loads((ROOT / 'testset' / 'cases.json').read_text())}


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as cl:
        yield cl


@pytest.fixture(scope='module')
def h(client) -> dict[str, str]:
    """Токен API-клиента: анонимный лимит автопрогонов общий на процесс, тесты его не тратят."""
    tok = client.post('/api/v1/auth/login', json={'user_id': 'u-api', 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


# --------------------------------------------------------------------------- параллельная генерация
async def _approved_doc():
    """Каркас кейса 3 (ДПП ПК, 72 ч) без модели, утверждённый как в автопрогоне."""
    from app.agent import workflow as wf
    from app.core.errors import Conflict
    from app.programs.schemas import ProgramDoc, Status

    doc = ProgramDoc(id='prg-race', request=CASES[3]['request'], mode='auto')
    await wf.intake_step(doc, [], '')
    wf.fill_defaults(doc)
    await wf.skeleton_step(doc)
    try:
        wf.approve_skeleton(doc, 'auto-approve', auto=True)
    except Conflict:
        doc.status = Status.SKELETON_APPROVED
    return doc


def _kit_signature(doc) -> dict:
    k = doc.kit
    return {
        'module_programs': [mp.module_id for mp in k.module_programs],
        'questions': [(q.id, q.module_id) for q in k.questions],
        'tasks': [(t.id, t.module_id) for t in k.tasks],
        'lectures': [(lec.id, lec.module_id, len(lec.slides)) for lec in k.lectures],
        'assessments': [a.id for a in k.assessments],
        'tokens': (doc.usage.tokens_in, doc.usage.tokens_out, doc.usage.calls),
    }


async def test_parallel_generation_is_deterministic(client, monkeypatch) -> None:
    """SPEC-FLOW-38

    Навык content подменён: случайные задержки до и после учёта токенов, первый прогон — в обратном порядке
    завершения. Комплект, id и суммы токенов одинаковы во всех прогонах и совпадают с ожидаемыми.
    """
    from app.agent import workflow as wf

    base = await _approved_doc()
    n_mod = len(base.modules)
    assert n_mod >= 3
    real = wf.content

    def fake_factory(delays: dict[str, float], finished: list[str]):
        async def fake_run(doc, m, *, n_questions, test_id, slide_topics, stats=None, instruction_extra=''):
            await asyncio.sleep(delays[m.id])
            stats.add('content', 1000 * m.n, 10 * m.n, 0.01 * m.n)
            await asyncio.sleep(delays[m.id] / 2)
            stats.add('content', 1, 1, 0.0)
            finished.append(m.id)
            return real.fallback(doc, m, real._module_los(doc, m), n_questions, test_id, slide_topics)

        return fake_run

    signatures, orders = [], []
    for run_no in range(4):
        rnd = random.Random(run_no)
        if run_no == 0:
            delays = {m.id: 0.004 * (n_mod - i) for i, m in enumerate(base.modules)}  # последний модуль завершается первым
        else:
            delays = {m.id: rnd.uniform(0, 0.02) for m in base.modules}
        finished: list[str] = []
        monkeypatch.setattr(real, 'run', fake_factory(delays, finished))
        doc = base.model_copy(deep=True)
        before = (doc.usage.tokens_in, doc.usage.tokens_out, doc.usage.calls)
        await wf.generate_kit(doc)
        orders.append(finished)
        sig = _kit_signature(doc)
        exp_in = sum(1000 * m.n + 1 for m in doc.modules)
        exp_out = sum(10 * m.n + 1 for m in doc.modules)
        assert sig['tokens'] == (before[0] + exp_in, before[1] + exp_out, before[2] + 2 * n_mod)
        assert doc.usage.by_skill['content']['calls'] >= 2 * n_mod
        # Порядок слияния — порядок модулей каркаса
        assert sig['module_programs'] == [m.id for m in doc.modules]
        mod_order = {m.id: i for i, m in enumerate(doc.modules)}
        assert [mod_order[mid] for _, mid in sig['questions']] == sorted(mod_order[mid] for _, mid in sig['questions'])
        signatures.append(sig)
    assert orders[0] == [m.id for m in reversed(base.modules)]  # задачи действительно завершались не по порядку
    assert all(s == signatures[0] for s in signatures[1:])


async def test_module_failure_is_isolated_and_recorded(client, monkeypatch) -> None:
    """SPEC-FLOW-39"""
    from app.agent import workflow as wf
    from app.programs.schemas import Status

    doc = await _approved_doc()
    real = wf.content
    bad = doc.modules[1].id

    async def flaky(d, m, *, n_questions, test_id, slide_topics, stats=None, instruction_extra=''):
        if m.id == bad:
            raise RuntimeError('сбой разбора в модуле')
        return real.fallback(d, m, real._module_los(d, m), n_questions, test_id, slide_topics)

    monkeypatch.setattr(real, 'run', flaky)
    await wf.generate_kit(doc)
    assert doc.status == Status.KIT_READY
    assert [mp.module_id for mp in doc.kit.module_programs] == [m.id for m in doc.modules]
    assert any(q.module_id == bad for q in doc.kit.questions) and bad in doc.kit.drafts
    errs = [e for e in doc.step_errors if e.module == bad]
    assert len(errs) == 1 and errs[0].step == 'kit' and errs[0].skill == 'content'
    assert errs[0].error.startswith('RuntimeError') and 'шаблон' in errs[0].fallback
    assert any('Навык content (модуль' in n for n in doc.agent_notes)


# --------------------------------------------------------------------------- слайды без модели
def _module_slides(client, h, pid: str, module_n: int) -> tuple[list, int]:
    from pptx import Presentation

    prog = client.get(f'/api/v1/programs/{pid}', headers=h).json()
    m1 = next(m['id'] for m in prog['modules'] if m['n'] == module_n)
    lectures = [lec for lec in prog['kit']['lectures'] if lec['module_id'] == m1 and lec['slides']]
    r = client.get(f'/api/v1/programs/{pid}/export/pptx', headers=h)
    assert r.status_code == 200 and r.content[:2] == b'PK'
    prs = Presentation(io.BytesIO(r.content))
    slides = list(prs.slides)
    titles = [s.shapes.title.text for s in slides]
    for lec in lectures:
        for sl in lec['slides']:
            assert sl['title'] in titles
    return lectures, len(slides)


def _assert_module_deck(client, h, pid: str, module_n: int = 1) -> None:
    lectures, n_slides = _module_slides(client, h, pid, module_n)
    assert lectures, f'нет слайдов модуля {module_n}'
    first = lectures[0]['slides']
    assert len(first) >= 4  # титул темы и не меньше трёх слайдов с тезисами
    assert all(s['title'].strip() for s in first)
    assert sum(1 for s in first[1:] if any(b.strip() for b in s['bullets'])) >= 3
    assert n_slides >= 1 + len(first)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(client.get(f'/api/v1/programs/{pid}/export/pptx', headers=h).content))
    deck = list(prs.slides)
    start = next(i for i, sl in enumerate(deck) if sl.shapes.title.text == first[0]['title'])
    body = deck[start:start + len(first)]
    assert [sl.shapes.title.text for sl in body] == [x['title'] for x in first]
    assert all(sl.placeholders[1].text_frame.text.strip() for sl in body)  # у каждого слайда модуля есть тезисы


@pytest.mark.parametrize('case_id,ptype,module_n', [
    (2, 'dpp_pk', 1),  # ДПП ПК, слайды не заказаны — первый модуль (допущение профиля)
    (1, 'doop', 1),    # ДООП, слайды первых двух занятий
    (3, 'dpp_pk', 2),  # ДПП ПК, слайды заказаны для модуля про pandas
])
def test_pptx_slides_without_llm(client, h, case_id: int, ptype: str, module_n: int) -> None:
    """SPEC-FLOW-40"""
    case = CASES[case_id]
    r = client.post('/api/v1/programs?mode=auto', json={'request': case['request'], 'answers': case['answers']}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j['skeleton']['type'] == ptype
    _assert_module_deck(client, h, j['program_id'], module_n)


def test_pptx_slides_when_content_skill_unavailable(client, h, monkeypatch) -> None:
    """SPEC-FLOW-40, SPEC-CONTENT-13

    Модель «включена», но каждый вызов content заканчивается LLMUnavailable: слайды первого модуля собираются
    по каркасу, отказы видны в step_errors.
    """
    from app.skills.content import run as content_mod

    class Down:
        enabled = True

        async def complete_json(self, **kw):
            raise c.LLMUnavailable('content: модель не ответила (GatewayError: HTTP 503)')

    monkeypatch.setattr(content_mod, 'get_llm', lambda: Down())
    case = CASES[3]
    j = client.post('/api/v1/programs?mode=auto', json={'request': case['request'], 'answers': case['answers']}, headers=h).json()
    assert j['status'] in ('done', 'done_with_errors')
    errs = [e for e in j['step_errors'] if e['skill'] == 'content']
    assert len(errs) == len(j['skeleton']['modules']) and all('LLMUnavailable' in e['error'] for e in errs)
    _assert_module_deck(client, h, j['program_id'], 2)


async def test_slides_guaranteed_when_content_returns_none(client, monkeypatch) -> None:
    """SPEC-FLOW-40: даже если навык content не вернул ни одной лекции со слайдами, комплект получает слайды заказанного модуля из каркаса."""
    from app.agent import workflow as wf

    doc = await _approved_doc()
    real = wf.content

    async def no_slides(d, m, *, n_questions, test_id, slide_topics, stats=None, instruction_extra=''):
        res = real.fallback(d, m, real._module_los(d, m), n_questions, test_id, slide_topics)
        res.lectures = []
        return res

    monkeypatch.setattr(real, 'run', no_slides)
    await wf.generate_kit(doc)
    target = next(m for m in doc.modules if m.n in doc.params.materials.slides_modules)  # заказанный модуль (в кейсе 3 — второй)
    with_slides = [lec for lec in doc.kit.lectures if lec.slides]
    assert with_slides and all(lec.module_id == target.id for lec in with_slides)
    assert all(len(lec.slides) >= 4 for lec in with_slides)


# --------------------------------------------------------------------------- шаг clarify
def test_interactive_returns_questions_and_resumes(client, h) -> None:
    """SPEC-API-25"""
    case = CASES[4]
    r = client.post('/api/v1/programs', json={'request': case['request']}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j['status'] == 'questions' and j['needs_answers'] is True
    assert j['answers_url'].endswith(f'/api/v1/programs/{j["program_id"]}/answers')
    fields = [q['field'] for q in j['questions']]
    assert 'program_type' in fields and 'volume_h' in fields and len(fields) <= 5
    assert all(len(q['options']) >= 2 for q in j['questions'])
    assert j['program']['modules'] == []  # конвейер стоит до ответов
    r = client.post(f'/api/v1/programs/{j["program_id"]}/answers?wait=true', json={'answers': case['answers']}, headers=h)
    assert r.status_code == 200
    k = r.json()
    assert k['status'] == 'skeleton'
    assert k['program']['volume_h'] == 72 and k['program']['type'] == 'dpp_pk' and len(k['program']['modules']) >= 3
    assert not any(a['field'] in ('program_type', 'volume_h') for a in k['assumptions'])


def test_answers_then_auto_completes_kit(client, h) -> None:
    """SPEC-API-25: ответы через API и ?mode=auto — конвейер идёт до комплекта и отвечает в формате автопрогона."""
    case = CASES[4]
    pid = client.post('/api/v1/programs', json={'request': case['request']}, headers=h).json()['program_id']
    r = client.post(f'/api/v1/programs/{pid}/answers?mode=auto', json={'answers': {'program_type': 'Повышение квалификации', 'volume_h': '72'}}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j['status'] in ('done', 'done_with_errors') and j['skeleton']['totals']['all'] == 72
    skipped = {q['field'] for q in j['questions_skipped']}
    asked = {q['field']: q for q in j['questions_asked']}
    assert {'program_type', 'volume_h'} <= set(asked) and len(asked) <= 5 and asked['volume_h']['answer'] == '72'
    assumed = {a['field'] for a in j['assumptions']}
    assert 'program_type' not in skipped and 'volume_h' not in skipped
    assert skipped and skipped <= assumed  # неотвеченные вопросы закрыты значениями профиля и перечислены


def test_answers_endpoint_checks_owner(client, h) -> None:
    """SPEC-API-25: ответы на чужую программу API-клиент дать не может."""
    tok = client.post('/api/v1/auth/login', json={'user_id': 'u-madina', 'password': 'demo'}).json()['access_token']
    pid = client.post('/api/v1/programs', json={'request': CASES[4]['request']}, headers={'Authorization': f'Bearer {tok}'}).json()['program_id']
    r = client.post(f'/api/v1/programs/{pid}/answers', json={'answers': {}}, headers=h)
    assert r.status_code == 403


def test_auto_lists_assumptions_for_missing_fields(client, h) -> None:
    """SPEC-API-26"""
    r = client.post('/api/v1/programs?mode=auto', json={'request': CASES[4]['request']}, headers=h)
    assert r.status_code == 200
    j = r.json()
    by_field = {a['field']: a for a in j['assumptions']}
    for f in ('program_type', 'volume_h'):
        assert f in by_field and by_field[f]['value'] not in (None, '') and by_field[f]['source']
    assert {'program_type', 'volume_h'} <= {q['field'] for q in j['questions_skipped']}
    assert [q['field'] for q in j['questions_asked']] == [q['field'] for q in j['questions_skipped']]  # ответов не было
    assert isinstance(j['step_errors'], list)
    assert j['skeleton']['volume_h'] == int(by_field['volume_h']['value'])


# --------------------------------------------------------------------------- LLM: учёт, таймауты, повторы
def test_call_stats_threadsafe_and_merge() -> None:
    """SPEC-LLM-21"""
    st = c.CallStats()

    def work() -> None:
        for _ in range(2000):
            st.add('content', 1, 2, 0.001)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (st.tokens_in, st.tokens_out, st.calls) == (16000, 32000, 16000)
    assert st.by_skill['content']['calls'] == 16000
    other = c.CallStats()
    other.add('judge', 5, 6, 1.0)
    other.fallback('judge', c.LLMUnavailable('x'), 'оценки кодом')
    st.merge(other)
    assert st.calls == 16001 and st.by_skill['judge'] == {'tokens_in': 5, 'tokens_out': 6, 'cost_rub': 1.0, 'calls': 1}
    assert st.fallbacks == [{'skill': 'judge', 'module': '', 'error': 'LLMUnavailable: x', 'fallback': 'оценки кодом'}]


class _EmbedGateway:
    def __init__(self, *items) -> None:
        self.items, self.calls = list(items), 0
        gw = self

        class _E:
            @staticmethod
            async def create(**kw):
                gw.calls += 1
                item = gw.items.pop(0) if gw.items else None
                if isinstance(item, Exception):
                    raise item
                return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0]) for _ in kw['input']], usage=SimpleNamespace(prompt_tokens=1))

        self.embeddings = _E


@pytest.fixture
def llm_factory(tmp_path, monkeypatch):
    from app.core.config import Settings

    def _make(gateway, **over) -> c.LLMClient:
        base = {'data_dir': tmp_path, 'llm_providers': 'cloudru', 'llm_api_key': 'k', 'llm_model_generate': 'gen',
                'llm_model_reserve': 'reserve', 'llm_model_judge': 'judge-m', 'llm_timeout_s': 120.0}
        s = Settings().model_copy(update=base | over)
        monkeypatch.setattr(c, 'get_settings', lambda: s)
        llm = c.LLMClient()
        llm._client = gateway
        return llm

    return _make


@pytest.fixture
def pauses(monkeypatch) -> list[float]:
    got: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s: float) -> None:
        got.append(s)
        await real_sleep(0)

    monkeypatch.setattr(c.asyncio, 'sleep', fake_sleep)
    return got


def test_embed_retries_transient(llm_factory, pauses) -> None:
    """SPEC-LLM-22"""
    gw = _EmbedGateway(c.GatewayError('HTTP 503', 503), c.GatewayError('Таймаут шлюза'), None)
    out = asyncio.run(llm_factory(gw).embed(['a', 'b']))
    assert out == [[1.0], [1.0]] and gw.calls == 3 and pauses == [1.0, 3.0]
    gw = _EmbedGateway(*[c.GatewayError('HTTP 502', 502)] * 3)
    with pytest.raises(c.LLMUnavailable, match='embed: модель не ответила'):
        asyncio.run(llm_factory(gw).embed(['a']))
    assert gw.calls == 3


def test_embed_no_retry_on_auth_and_limit(llm_factory, pauses) -> None:
    """SPEC-LLM-22"""
    gw = _EmbedGateway(c.GatewayError('HTTP 401', 401))
    with pytest.raises(c.LLMUnavailable, match='401'):
        asyncio.run(llm_factory(gw).embed(['a']))
    assert gw.calls == 1
    gw = _EmbedGateway(c.GatewayError('HTTP 429', 429, {'code': 'llm_daily_limit_exceeded'}))
    llm = llm_factory(gw)
    with pytest.raises(c.LLMUnavailable, match='лимит'):
        asyncio.run(llm.embed(['a']))
    assert gw.calls == 1 and llm.limit_reached() and pauses == []


def test_ping_timeout_and_malformed_response(llm_factory, pauses) -> None:
    """SPEC-LLM-23"""

    class Hang:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    await asyncio.Event().wait()

    r = asyncio.run(llm_factory(Hang(), llm_timeout_s=0.05).ping())
    assert r['enabled'] and r['ok'] is False and r['error'] == 'TimeoutError'

    good = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))], usage=None)
    seq = [SimpleNamespace(choices=[]), good]
    calls = []

    class Odd:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw['model'])
                    return seq.pop(0)

    assert asyncio.run(llm_factory(Odd()).complete_json(skill='t', system='s', user='u')) == {'a': 1}
    assert calls == ['gen', 'gen'] and pauses == [1.0]
