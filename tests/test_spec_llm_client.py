"""Спецификация specs/llm-client.md: клиент шлюза Cloud.ru (ТЗ 4.11, NFR-08)."""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.core.config import Settings  # noqa: E402
from app.llm import client as c  # noqa: E402


class Out(BaseModel):
    answer: str


class HTTPError(c.GatewayError):
    def __init__(self, code: int, body: object = '') -> None:
        super().__init__(f'HTTP {code}', code, body)


def _resp(content: str, tin: int = 1000, tout: int = 500):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                           usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout))


class Gateway:
    """Подменный шлюз: отдаёт ответы или исключения по очереди и пишет вызовы."""

    def __init__(self, *items) -> None:
        self.items, self.calls = list(items), []
        gw = self

        class _Completions:
            @staticmethod
            async def create(**kw):
                gw.calls.append(kw)
                item = gw.items.pop(0) if len(gw.items) > 1 else gw.items[0]
                if isinstance(item, Exception):
                    raise item
                return item

        class _Embeddings:
            @staticmethod
            async def create(**kw):
                gw.calls.append(kw)
                return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(t))]) for t in kw['input']],
                                       usage=SimpleNamespace(prompt_tokens=len(kw['input'])))

        self.chat = SimpleNamespace(completions=_Completions)
        self.embeddings = _Embeddings


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    got: list[float] = []

    async def fake_sleep(s: float) -> None:
        got.append(s)

    monkeypatch.setattr(c.asyncio, 'sleep', fake_sleep)
    return got


@pytest.fixture
def make(tmp_path, monkeypatch):
    def _make(gateway: Gateway | None = None, **over) -> c.LLMClient:
        base = {'data_dir': tmp_path, 'llm_providers': 'cloudru', 'llm_api_key': 'k',
                'llm_model_generate': 'gen', 'llm_model_reserve': 'reserve', 'llm_model_judge': 'judge-m',
                'llm_daily_budget_rub': 90.0, 'llm_timeout_s': 120.0}
        s = Settings().model_copy(update=base | over)
        monkeypatch.setattr(c, 'get_settings', lambda: s)
        llm = c.LLMClient()
        if gateway is not None:
            llm._client = gateway
        return llm

    return _make


def _run(coro):
    return asyncio.run(coro)


def test_parse_json_cleanup() -> None:
    """SPEC-LLM-01: parse_json снимает <think>, обрамление ```json, текст вокруг JSON и висячие запятые."""
    assert c.parse_json('<think>x</think>Вот ответ:\n```json\n{"a": [1, 2,],}\n```') == {'a': [1, 2]}
    assert c.parse_json('Ответ: [1, 2] спасибо') == [1, 2]
    with pytest.raises(json.JSONDecodeError):
        c.parse_json('нет json')


def test_daily_limit_detection() -> None:
    """SPEC-LLM-02: суточный лимит распознаётся только у 429 с признаком daily/spending limit в тексте или теле."""
    assert c.is_daily_limit(HTTPError(429, {'code': 'llm_daily_limit_exceeded'}))
    assert c.is_daily_limit(HTTPError(429, 'Daily spending limit'))
    assert not c.is_daily_limit(HTTPError(429, 'too many requests'))
    assert not c.is_daily_limit(HTTPError(500, 'daily'))


def test_call_stats_accumulate() -> None:
    """SPEC-LLM-03: CallStats суммирует токены, рубли и вызовы, в том числе по навыкам."""
    st = c.CallStats()
    st.add('content', 10, 5, 0.5)
    st.add('content', 1, 1, 0.25)
    st.add('judge', 2, 2, 1.0)
    assert (st.tokens_in, st.tokens_out, st.calls, st.cost_rub) == (13, 8, 3, 1.75)
    assert st.by_skill['content'] == {'tokens_in': 11, 'tokens_out': 6, 'cost_rub': 0.75, 'calls': 2}


def test_disabled_and_budget_guards(make) -> None:
    """SPEC-LLM-04: IF модель не настроена или дневной бюджет исчерпан, THEN complete_json сразу бросает LLMUnavailable, не обращаясь к шлюзу."""
    gw = Gateway(_resp('{"answer": "x"}'))
    off = make(gw, llm_providers='fixtures')
    with pytest.raises(c.LLMUnavailable, match='не настроен'):
        _run(off.complete_json(skill='t', system='s', user='u'))
    llm = make(gw)
    llm._day, llm._spent = c._today(), 95.0
    with pytest.raises(c.LLMUnavailable, match='бюджет'):
        _run(llm.complete_json(skill='t', system='s', user='u'))
    assert gw.calls == []


def test_success_validates_and_accounts(make, tmp_path) -> None:
    """SPEC-LLM-05: успешный ответ проверяется схемой; токены и стоимость учитываются в CallStats и в суточном расходе (файл в data_dir)."""
    gw = Gateway(_resp('```json\n{"answer": "ок"}\n```', tin=1_000_000, tout=0))
    llm = make(gw, llm_price_in_rub=10.0)
    st = c.CallStats()
    out = _run(llm.complete_json(skill='content', system='s', user='u', schema=Out, stats=st, max_tokens=77, temperature=0.4))
    assert out == Out(answer='ок')
    assert gw.calls[0]['model'] == 'gen' and gw.calls[0]['max_tokens'] == 77 and gw.calls[0]['temperature'] == 0.4
    assert st.cost_rub == pytest.approx(10.0) and st.by_skill['content']['calls'] == 1
    assert llm.spent_today() == pytest.approx(10.0)
    saved = json.loads((tmp_path / 'llm_spend.json').read_text())
    assert saved['day'] == c._today() and saved['rub'] == 10.0
    assert llm.status['generate']['ok'] is True
    assert _run(make(Gateway(_resp('{"a": 1}'))).complete_json(skill='t', system='s', user='u')) == {'a': 1}


def test_invalid_json_feedback_then_success(make, sleeps) -> None:
    """SPEC-LLM-06: WHEN ответ не прошёл схему, модели отправляются её ответ и текст ошибки, это одна из попыток (пауза 1 с)."""
    gw = Gateway(_resp('{"wrong": 1}'), _resp('{"answer": "ok"}'))
    out = _run(make(gw).complete_json(skill='t', system='s', user='u', schema=Out))
    assert out.answer == 'ok'
    msgs = gw.calls[1]['messages']
    assert [m['role'] for m in msgs] == ['system', 'user', 'assistant', 'user']
    assert 'не прошёл проверку схемы' in msgs[3]['content']
    assert sleeps == [1.0]


def test_empty_answer_repeats_original(make, sleeps) -> None:
    """SPEC-LLM-07: WHEN ответ пустой (только рассуждение), повторяется исходный запрос без сообщения ассистента."""
    gw = Gateway(_resp('<think>долго думал'), _resp('{"answer": "ok"}'))
    _run(make(gw).complete_json(skill='t', system='s', user='u', schema=Out))
    assert len(gw.calls[1]['messages']) == 2


def test_server_errors_retry_then_reserve(make, sleeps) -> None:
    """SPEC-LLM-08: при 5xx — до 3 попыток с паузами 1 и 3 с, затем резервная модель; после всех — LLMUnavailable с типом ошибки."""
    gw = Gateway(HTTPError(500))
    llm = make(gw)
    with pytest.raises(c.LLMUnavailable, match=r'модель не ответила \(HTTPError: HTTP 500\)'):
        _run(llm.complete_json(skill='t', system='s', user='u'))
    assert [k['model'] for k in gw.calls] == ['gen'] * 3 + ['reserve'] * 3
    assert sleeps == [1.0, 3.0, 1.0, 3.0]
    assert llm.status['generate'] == {'model': 'reserve', 'ok': False, 'error': 'HTTPError', 'status': 500}


def test_auth_error_goes_to_reserve(make, sleeps) -> None:
    """SPEC-LLM-09: WHEN ошибка авторизации (401/403), клиент сразу переходит к резервной модели."""
    gw = Gateway(HTTPError(401), _resp('{"answer": "r"}'))
    out = _run(make(gw).complete_json(skill='t', system='s', user='u', schema=Out))
    assert out.answer == 'r' and [k['model'] for k in gw.calls] == ['gen', 'reserve'] and sleeps == []


def test_overload_429_backoff(make, sleeps) -> None:
    """SPEC-LLM-10: WHEN 429 без признака суточного лимита, пауза 15 × (номер попытки + 1) с, затем повтор."""
    gw = Gateway(HTTPError(429, 'busy'), HTTPError(429, 'busy'), _resp('{"answer": "ok"}'))
    _run(make(gw).complete_json(skill='t', system='s', user='u'))
    assert sleeps == [15.0, 1.0, 30.0, 3.0] and len(gw.calls) == 3


def test_daily_limit_no_retries(make, sleeps, tmp_path) -> None:
    """SPEC-LLM-11: WHEN шлюз ответил «суточный лимит», лимит отмечается до 00:00 МСК, без повторов и резерва, следующие вызовы не идут в шлюз."""
    gw = Gateway(HTTPError(429, 'daily spending limit is reached'))
    llm = make(gw)
    with pytest.raises(c.LLMUnavailable, match='лимит'):
        _run(llm.complete_json(skill='t', system='s', user='u'))
    assert len(gw.calls) == 1 and llm.limit_reached()
    assert json.loads((tmp_path / 'llm_spend.json').read_text())['limit_day'] == c._today()
    with pytest.raises(c.LLMUnavailable):
        _run(llm.complete_json(skill='t', system='s', user='u'))
    assert len(gw.calls) == 1


def test_judge_role_single_attempt_then_generate(make, sleeps) -> None:
    """SPEC-LLM-12: роль judge — одна попытка модели-судьи, затем модель генерации как резерв; цена судьи — по тарифу судьи."""
    gw = Gateway(HTTPError(503), _resp('{"answer": "g"}'))
    llm = make(gw)
    _run(llm.complete_json(skill='judge', role='judge', system='s', user='u', schema=Out))
    assert [k['model'] for k in gw.calls] == ['judge-m', 'gen']
    assert llm._price('judge-m') == (llm.settings.llm_judge_price_in_rub, llm.settings.llm_judge_price_out_rub)
    assert llm._price('gen') == (llm.settings.llm_price_in_rub, llm.settings.llm_price_out_rub)
    assert make(None, llm_model_reserve='gen')._models('generate') == ['gen']


def test_time_budget_exhausted(make, monkeypatch) -> None:
    """SPEC-LLM-13: IF бюджет времени навыка исчерпан, THEN LLMUnavailable без нового запроса к шлюзу."""
    gw = Gateway(_resp('{"answer": "x"}'))
    monkeypatch.setattr(c, '_budget_s', lambda skill, default: 0.0)
    with pytest.raises(c.LLMUnavailable, match='бюджет времени'):
        _run(make(gw).complete_json(skill='t', system='s', user='u'))
    assert gw.calls == []


def test_budget_from_skill_md() -> None:
    """SPEC-LLM-14: бюджет времени = timeout_s × (retries + 1) из SKILL.md, для навыка без SKILL.md — llm_timeout_s × 3."""
    from app.skills.base import load_skills

    spec = load_skills()['content']
    assert c._budget_s('content', 1.0) == spec.timeout_s * (spec.retries + 1)
    assert c._budget_s('нет-такого', 120.0) == 360.0


def test_spend_persists_and_resets_daily(make, tmp_path) -> None:
    """SPEC-LLM-15: расход за сутки переживает перезапуск, обнуляется с новыми сутками по МСК; повреждённый файл не мешает запуску."""
    llm = make()
    llm._spend(2.5)
    assert make().spent_today() == 2.5
    llm._day = '2000-01-01'
    assert llm.spent_today() == 0.0
    llm._spend(1.0)
    assert llm.spent_today() == 1.0
    (tmp_path / 'llm_spend.json').write_text('{broken')
    assert make().spent_today() == 0.0


def test_spend_write_failure_tolerated(make, tmp_path) -> None:
    """SPEC-LLM-16: IF файл расхода нельзя записать, THEN клиент продолжает работу без исключения."""
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    llm = make(data_dir=blocker / 'sub')
    llm._spend(1.0)
    assert llm.spent_today() == 1.0


def test_embed_batches(make) -> None:
    """SPEC-LLM-17: embed отправляет тексты пачками по 16 и учитывает входные токены под именем embed со стоимостью 0."""
    gw = Gateway()
    st = c.CallStats()
    out = _run(make(gw).embed(['a' * i for i in range(1, 21)], stats=st))
    assert len(out) == 20 and out[0] == [1.0]
    assert [len(k['input']) for k in gw.calls] == [16, 4]
    assert st.by_skill['embed'] == {'tokens_in': 20, 'tokens_out': 0, 'cost_rub': 0.0, 'calls': 2}


def test_embed_guards(make) -> None:
    """SPEC-LLM-18: IF модель не настроена или суточный лимит исчерпан, THEN embed бросает LLMUnavailable."""
    with pytest.raises(c.LLMUnavailable):
        _run(make(Gateway(), llm_providers='fixtures').embed(['x']))
    llm = make(Gateway())
    llm._mark_limit()
    with pytest.raises(c.LLMUnavailable):
        _run(llm.embed(['x']))


def test_ping(make) -> None:
    """SPEC-LLM-19: ping сообщает статус модели; успешный ответ сбрасывает отметку лимита, ответ «суточный лимит» её ставит."""
    assert _run(make(Gateway(), llm_providers='fixtures').ping()) == {'enabled': False, 'provider': 'fixtures'}
    llm = make(Gateway(_resp('ок')))
    llm._mark_limit()
    r = _run(llm.ping())
    assert r['ok'] and r['model'] == 'gen' and not llm.limit_reached()
    bad = make(Gateway(HTTPError(429, 'daily limit')))
    r = _run(bad.ping())
    assert r == {'enabled': True, 'ok': False, 'error': 'HTTPError', 'daily_limit_reached': True}


def test_gateway_client_lazy_and_singleton(make, monkeypatch) -> None:
    """SPEC-LLM-20: клиент шлюза Cloud.ru создаётся лениво с адресом и таймаутом из настроек и без встроенных повторов; get_llm возвращает один экземпляр."""
    llm = make(llm_base_url='http://gw.local/v1', llm_timeout_s=33.0)
    cl = llm._get()
    assert cl is llm._get() and str(cl.base_url).startswith('http://gw.local/v1') and cl.max_retries == 0 and cl.timeout == 33.0
    monkeypatch.setattr(c, '_client', None)
    assert c.get_llm() is c.get_llm()


def test_gateway_http_errors_and_no_foreign_sdk() -> None:
    """SPEC-LLM-20: клиент шлюза Cloud.ru работает на httpx без сторонних SDK; HTTP-ошибка несёт статус и тело."""
    import asyncio
    from pathlib import Path

    import httpx

    from app.llm.gateway import CloudRuGateway, GatewayError

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers['Authorization'] == 'Bearer k' and request.url.path.endswith('/chat/completions')
        if b'"bad"' in request.content:
            return httpx.Response(429, json={'message': 'daily spending limit'})
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"answer":"ok"}'}}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 2}})

    gw = CloudRuGateway('http://gw.local/v1', 'k', 10.0)
    gw._http = httpx.AsyncClient(base_url=gw.base_url, transport=httpx.MockTransport(handler), headers={'Authorization': 'Bearer k'})
    resp = asyncio.run(gw.chat.completions.create(model='m', messages=[]))
    assert resp.choices[0].message.content == '{"answer":"ok"}' and resp.usage.prompt_tokens == 3
    try:
        asyncio.run(gw.chat.completions.create(model='bad', messages=[]))
    except GatewayError as exc:
        assert exc.status_code == 429 and c.is_daily_limit(exc)
    else:
        raise AssertionError('ожидалась GatewayError')
    root = Path(__file__).resolve().parents[1]
    deps = (root / 'requirements.txt').read_text(encoding='utf-8').lower()
    assert not any(name in deps for name in ('openai', 'anthropic', 'google-generativeai', 'mistralai', 'cohere'))


class Many(BaseModel):
    annotation: str
    questions: list[dict] = []


def test_truncated_answer_salvaged_when_partial_ok(make, sleeps) -> None:
    """SPEC-LLM-24: IF ответ оборван и исправления не помогли, а навык разрешил частичный ответ (partial_ok), THEN THE SYSTEM SHALL вернуть его целую часть и записать отказ в step_errors; без partial_ok — LLMUnavailable."""
    cut = '{"annotation": "Модуль", "questions": [{"stem": "Что?", "key": 0}, {"stem": "Где, ке'
    st = c.CallStats()
    out = _run(make(Gateway(_resp(cut))).complete_json(skill='content', system='s', user='u', schema=Many, stats=st, partial_ok=True))
    assert out.annotation == 'Модуль' and out.questions == [{'stem': 'Что?', 'key': 0}]
    assert st.fallbacks and 'оборван' in st.fallbacks[-1]['error']
    with pytest.raises(c.LLMUnavailable):
        _run(make(Gateway(_resp(cut))).complete_json(skill='content', system='s', user='u', schema=Many))
    assert c.parse_json('{"a": [1, 2', salvage=True) == {'a': [1]}
    with pytest.raises(json.JSONDecodeError):
        c.parse_json('{"a": [1, 2')


def test_budget_checked_after_queue(make) -> None:
    """SPEC-LLM-25"""
    gw = Gateway(_resp('{"answer": "ok"}'))
    llm = make(gw, llm_concurrency=1, llm_daily_budget_rub=0.01)

    async def scenario() -> None:
        async with llm._sem:
            # вызов заходит в очередь, пока семафор удержан; pre-check бюджета ещё проходит
            task = asyncio.create_task(llm.complete_json(skill='content', system='s', user='u', schema=Out))
            await asyncio.sleep(0.01)
            assert llm.spent_today() < llm.settings.llm_daily_budget_rub
            llm._spend(0.5)  # бюджет исчерпан, пока вызов стоял в очереди
        await task

    with pytest.raises(c.LLMUnavailable) as exc:
        _run(scenario())
    assert 'бюджет' in str(exc.value)
    assert gw.calls == [], 'вызов не должен уходить в шлюз после исчерпания бюджета в очереди'


def test_ping_budget_and_spend(make) -> None:
    """SPEC-LLM-27: IF дневной бюджет исчерпан, THEN ping бросает LLMUnavailable до обращения к шлюзу."""
    llm = make(Gateway(_resp('ок', tin=1_000_000, tout=0)), llm_price_in_rub=10.0)
    llm._day, llm._spent = c._today(), 95.0
    with pytest.raises(c.LLMUnavailable, match='бюджет'):
        _run(llm.ping())
    assert llm._client.calls == [], 'ping не должен обращаться к шлюзу при исчерпанном бюджете'


def test_ping_accounts_cost_when_budget_allows(make) -> None:
    """SPEC-LLM-27: успешный ping списывает стоимость ответа по тарифу модели генерации и пишет статус generate."""
    gw = Gateway(_resp('ок', tin=1_000_000, tout=0))
    llm = make(gw, llm_price_in_rub=10.0)
    r = _run(llm.ping())
    assert r['ok'] is True and r['model'] == 'gen'
    assert llm.spent_today() == pytest.approx(10.0)
    assert llm.status['generate'] == {'model': 'gen', 'ok': True, 'latency_s': r['latency_s']}


def test_embed_budget_checked_per_batch(make, monkeypatch) -> None:
    """SPEC-LLM-27: бюджет проверяется перед сетевым вызовом каждой пачки эмбеддингов: исчерпан до старта — без вызова шлюза, исчерпан между пачками — вторая пачка не отправляется."""
    llm = make(Gateway())
    llm._day, llm._spent = c._today(), 95.0
    with pytest.raises(c.LLMUnavailable, match='бюджет'):
        _run(llm.embed(['x']))
    assert llm._client.calls == [], 'embed не должен обращаться к шлюзу при исчерпанном бюджете'

    gw = Gateway()
    llm = make(gw, llm_daily_budget_rub=90.0)
    state = {'batches': 0}

    def spent() -> float:
        return 95.0 if state['batches'] else 0.0

    def spend(cost: float) -> None:
        state['batches'] += 1

    monkeypatch.setattr(llm, 'spent_today', spent)
    monkeypatch.setattr(llm, '_spend', spend)
    with pytest.raises(c.LLMUnavailable, match='бюджет'):
        _run(llm.embed(['x'] * 20))  # две пачки: 16 + 4
    assert len(gw.calls) == 1, 'вторая пачка не уходит в шлюз после исчерпания бюджета'
