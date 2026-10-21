"""Слой моделей: клиент Cloud.ru Evolution Foundation Models / шлюза хакатона (ТЗ, 4.11).

Правила:
- повтор до 2 раз при ошибке, HTTP 5xx или невалидном JSON (паузы 1 и 3 с), при 429 — пауза 15, 30 с;
  затем резервная модель той же роли; при ошибке авторизации — сразу резерв;
- параллельность ограничена семафором, после 429 временно снижается;
- суточный лимит шлюза (429 «daily spending limit») — без повторов: до 00:00 МСК генерация по шаблонам;
- каждый вызов учитывает токены и рубли; ключ и тексты запросов не логируются;
- у каждого запроса к шлюзу есть таймаут (asyncio.wait_for поверх таймаута httpx): chat, embeddings, ping;
- наружу complete_json и embed отдают только LLMUnavailable — навык ловит его и включает резервную генерацию.
Стратегия целиком — docs/llm.md, раздел «Таймауты, повторы и отказы».
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.llm.gateway import CloudRuGateway, GatewayError

logger = logging.getLogger(__name__)

_RETRY_PAUSES = (1.0, 3.0)
_MSK = 3 * 3600
LIMIT_MSG = 'Дневной лимит шлюза LLM исчерпан, до 00:00 МСК модули собираются по шаблону'


def _today() -> str:
    """Сутки шлюза и бюджета считаются по Москве (UTC+3), а не по UTC контейнера."""
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + _MSK))


def is_daily_limit(exc: Exception) -> bool:
    """429 шлюза бывает двух видов: перегрузка (имеет смысл повторить) и исчерпанный суточный лимит."""
    if getattr(exc, 'status_code', None) != 429:
        return False
    text = f'{exc} {getattr(exc, "body", "")}'
    return bool(re.search(r'daily|spending limit|llm_daily_limit', text, flags=re.IGNORECASE))


class LLMUnavailable(Exception):
    """Ни одна модель роли не ответила после всех повторов."""


#: Ошибки обработки ответа модели в навыке: JSON прошёл схему, но не ложится в каркас
#: (нет нужного ключа, неверный индекс, пустое поле). Навык ловит их вместе с LLMUnavailable
#: и переходит на резервную генерацию; остальные исключения — ошибки кода и не глушатся.
MODEL_DATA_ERRORS: tuple[type[Exception], ...] = (ValidationError, ValueError, KeyError, IndexError, TypeError, AttributeError)

#: Повторяемые ошибки транспорта: сеть, таймаут, 429 (кроме суточного лимита), 5xx
_TRANSIENT = (GatewayError, asyncio.TimeoutError)


@dataclass
class CallStats:
    """Учёт вызовов одного шага. add() и merge() атомарны (под замком): статистику можно
    передавать в параллельные задачи и в потоки, суммы не теряются. Параллельная генерация
    модулей всё равно ведёт свой CallStats на модуль и сливает их по порядку модулей."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0
    calls: int = 0
    by_skill: dict[str, dict[str, float]] = field(default_factory=dict)
    # Отказы навыков на этом шаге: что упало и какая резервная генерация сработала
    fallbacks: list[dict[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, skill: str, tin: int, tout: int, cost: float, calls: int = 1) -> None:
        with self._lock:
            self.tokens_in += tin
            self.tokens_out += tout
            self.cost_rub += cost
            self.calls += calls
            s = self.by_skill.setdefault(skill, {'tokens_in': 0, 'tokens_out': 0, 'cost_rub': 0.0, 'calls': 0})
            s['tokens_in'] += tin
            s['tokens_out'] += tout
            s['cost_rub'] = round(s['cost_rub'] + cost, 4)
            s['calls'] += calls

    def merge(self, other: CallStats) -> None:
        """Добавляет статистику другой задачи (модуля) целиком, включая отказы навыков."""
        with other._lock:
            items = [(k, dict(v)) for k, v in other.by_skill.items()]
            fallbacks = list(other.fallbacks)
        for skill_name, s in items:
            self.add(skill_name, int(s['tokens_in']), int(s['tokens_out']), float(s['cost_rub']), calls=int(s['calls']))
        with self._lock:
            self.fallbacks += fallbacks

    def fallback(self, skill: str, error: Exception | str, used: str, module: str = '') -> None:
        """Фиксирует отказ навыка: структурная запись попадает в doc.step_errors и в отчёт автопрогона."""
        text = error if isinstance(error, str) else f'{type(error).__name__}: {str(error)[:200]}'
        with self._lock:
            self.fallbacks.append({'skill': skill, 'module': module, 'error': text, 'fallback': used})


def parse_json(text: str, salvage: bool = False) -> Any:
    """Снимает обрамление ```json, блоки рассуждений и лишние запятые, затем разбирает JSON.

    salvage=True: оборванный ответ закрывается по последнему целому значению (_close_truncated).
    """
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL).strip()  # рассуждение оборвано лимитом — ответа нет
    fence = re.search(r'```(?:json)?\s*(.*?)```', cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start = min((i for i in (cleaned.find('{'), cleaned.find('[')) if i >= 0), default=-1)
    if start > 0:
        cleaned = cleaned[start:]
    end = max(cleaned.rfind('}'), cleaned.rfind(']'))
    if end >= 0:
        cleaned = cleaned[: end + 1]
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        salvaged = _close_truncated(cleaned) if salvage else None
        if salvaged is None:
            raise
        return json.loads(salvaged)


def _close_truncated(text: str) -> str | None:
    """Ответ оборван лимитом токенов или шлюзом: отрезает незаконченный хвост до последнего целого
    значения и закрывает открытые скобки. Недостающее навык добирает по шаблону; None — спасать нечего."""
    stack: list[str] = []
    in_str = esc = False
    cut = -1  # позиция после последнего целого значения внутри объекта или массива
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
                if stack and stack[-1] == '[':
                    cut = i + 1
            continue
        if ch == '"':
            in_str = True
        elif ch in '{[':
            stack.append(ch)
        elif ch in '}]':
            if not stack:
                return None
            stack.pop()
            cut = i + 1
            if not stack:
                return None  # корень закрыт: обрыва нет, ошибка в другом
        elif ch == ',':
            cut = i
    if not stack or cut <= 0:
        return None
    head = text[:cut].rstrip().rstrip(',')
    # стек на позиции среза: заново по обрезанному тексту
    stack, in_str, esc = [], False, False
    for ch in head:
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in '{[':
            stack.append(ch)
        elif ch in '}]' and stack:
            stack.pop()
    if in_str or not stack:
        return None
    head = re.sub(r'[,:]\s*$', '', head)
    return head + ''.join('}' if b == '{' else ']' for b in reversed(stack))


def _budget_s(skill_name: str, default: float) -> float:
    from app.skills.base import load_skills

    spec = load_skills().get(skill_name)
    return spec.timeout_s * (spec.retries + 1) if spec else default * 3


class LLMClient:
    """Клиент ролей generate / judge с резервной моделью."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None
        self._sem = asyncio.Semaphore(max(1, self.settings.llm_concurrency))
        self._judge_sem = self._sem  # шлюз допускает 2 параллельных запроса на команду: общий лимит
        self.status: dict[str, Any] = {}
        self._day = ''
        self._spent = 0.0
        self._limit_day = ''
        self._load_spend()

    def _spend_file(self):
        return self.settings.data_dir / 'llm_spend.json'

    def _load_spend(self) -> None:
        try:
            data = json.loads(self._spend_file().read_text(encoding='utf-8'))
            self._day, self._spent = data.get('day', ''), float(data.get('rub', 0.0))
            self._limit_day = data.get('limit_day', '')
        except (OSError, ValueError):
            pass

    def _save_spend(self) -> None:
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            data = {'day': self._day, 'rub': round(self._spent, 4), 'limit_day': self._limit_day}
            self._spend_file().write_text(json.dumps(data), encoding='utf-8')
        except OSError:
            logger.warning('llm spend: не удалось записать расход')

    def _spend(self, cost: float) -> None:
        """Расход за сутки переживает перезапуск контейнера: файл в data_dir."""
        day = _today()
        if self._day != day:
            self._day, self._spent = day, 0.0
        self._spent += cost
        self._save_spend()

    def spent_today(self) -> float:
        return self._spent if self._day == _today() else 0.0

    def limit_reached(self) -> bool:
        """Шлюз ответил «суточный лимит исчерпан» сегодня (по МСК)."""
        return self._limit_day == _today()

    def _mark_limit(self) -> None:
        if not self.limit_reached():
            logger.warning('llm: суточный лимит шлюза исчерпан до 00:00 МСК')
        self._limit_day = _today()
        self._save_spend()

    @property
    def enabled(self) -> bool:
        return self.settings.llm_enabled

    def _get(self) -> Any:
        if self._client is None:
            self._client = CloudRuGateway(
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout_s,
            )
        return self._client

    def _models(self, role: str) -> list[str]:
        s = self.settings
        primary = s.llm_model_judge if role == 'judge' else s.llm_model_generate
        reserve = s.llm_model_generate if role == 'judge' else s.llm_model_reserve
        return [primary] if primary == reserve else [primary, reserve]

    def _price(self, model: str) -> tuple[float, float]:
        s = self.settings
        if model == s.llm_model_judge:
            return s.llm_judge_price_in_rub, s.llm_judge_price_out_rub
        return s.llm_price_in_rub, s.llm_price_out_rub

    async def complete_json(
        self,
        *,
        skill: str,
        system: str,
        user: str,
        schema: type[BaseModel] | None = None,
        role: str = 'generate',
        temperature: float = 0.2,
        max_tokens: int = 2000,
        stats: CallStats | None = None,
        partial_ok: bool = False,
    ) -> Any:
        """Вызывает модель и возвращает JSON, проверенный Pydantic-схемой навыка.

        partial_ok=True — навык умеет добрать недостающее по шаблону: если ответ оборван и исправление
        не помогло, на последней попытке берётся его целая часть, а не резервная генерация целиком.
        """
        if not self.enabled:
            raise LLMUnavailable('LLM не настроен')
        if self.limit_reached():
            raise LLMUnavailable(LIMIT_MSG)
        if self.spent_today() >= self.settings.llm_daily_budget_rub:
            raise LLMUnavailable(f'Дневной бюджет LLM {self.settings.llm_daily_budget_rub:.0f} ₽ исчерпан')
        sem = self._judge_sem if role == 'judge' else self._sem
        last_error: Exception | None = None
        # Бюджет времени навыка из SKILL.md (timeout_s × попытки): ожидание очереди шлюза не считается.
        # Исчерпан — навык уходит на резервную генерацию, и сроки FR-19/FR-31 держатся (подраздел 4.7)
        budget = _budget_s(skill, self.settings.llm_timeout_s)
        active = 0.0
        partial = ''  # последний оборванный ответ: при partial_ok спасается его целая часть

        def salvage() -> Any:
            try:
                data = parse_json(partial, salvage=True)
                out = schema.model_validate(data) if schema is not None else data
            except (json.JSONDecodeError, ValidationError):
                return None
            logger.warning('llm skill=%s: ответ оборван, взята целая часть (%d симв.)', skill, len(partial))
            if stats is not None:
                stats.fallback(skill, f'ответ модели оборван: {type(last_error).__name__}', 'целая часть ответа, недостающее по шаблону')
            return out
        for model in self._models(role):
            messages: list[dict[str, str]] = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
            # Ответ судьи дорогой и долгий (модель рассуждений): одна попытка, затем резервная модель
            attempts = 1 if model == self.settings.llm_model_judge else len(_RETRY_PAUSES) + 1
            for attempt in range(attempts):
                started = time.monotonic()
                if active >= budget:
                    if partial and (got := salvage()) is not None:
                        return got
                    raise LLMUnavailable(f'{skill}: бюджет времени {budget:.0f} с исчерпан')
                try:
                    async with sem:
                        # F15 (аудит 19.10): бюджет перепроверяется после ожидания в очереди —
                        # ждущие вызовы не отправляются, пока они стояли в очереди, бюджет мог исчерпаться.
                        if self.spent_today() >= self.settings.llm_daily_budget_rub:
                            raise LLMUnavailable(f'Дневной бюджет LLM {self.settings.llm_daily_budget_rub:.0f} ₽ исчерпан (проверка после очереди)')
                        started = time.monotonic()
                        try:
                            resp = await asyncio.wait_for(
                                self._get().chat.completions.create(
                                    model=model,
                                    messages=messages,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                ),
                                timeout=max(5.0, min(self.settings.llm_timeout_s, budget - active)),
                            )
                        finally:
                            active += time.monotonic() - started
                    try:
                        content = resp.choices[0].message.content or ''
                    except (AttributeError, IndexError, TypeError) as exc:
                        # Ответ шлюза без choices/message: повторяется как ошибка транспорта
                        raise GatewayError(f'Ответ шлюза без choices: {type(exc).__name__}') from exc
                    usage = getattr(resp, 'usage', None)
                    tin = int(getattr(usage, 'prompt_tokens', 0) or 0)
                    tout = int(getattr(usage, 'completion_tokens', 0) or 0)
                    pin, pout = self._price(model)
                    cost = (tin * pin + tout * pout) / 1_000_000
                    if stats is not None:
                        stats.add(skill, tin, tout, cost)
                    self._spend(cost)
                    logger.info(
                        'llm skill=%s model=%s in=%d out=%d latency=%.1fs attempt=%d',
                        skill, model, tin, tout, time.monotonic() - started, attempt,
                    )
                    self.status[role] = {'model': model, 'ok': True, 'latency_s': round(time.monotonic() - started, 2)}
                    data = parse_json(content)
                    if schema is not None:
                        return schema.model_validate(data)
                    return data
                except (json.JSONDecodeError, ValidationError) as exc:
                    last_error = exc
                    if partial_ok and isinstance(exc, json.JSONDecodeError):
                        partial = content
                    if not re.sub(r'<think>.*?(</think>|$)', '', content, flags=re.DOTALL).strip():
                        # Пустой ответ (модель рассуждений израсходовала лимит): повтор исходного запроса,
                        # пустое сообщение ассистента шлюз отклоняет с 400
                        messages = messages[:2]
                    else:
                        # Модель получает текст ошибки и исправляет ответ — это одна из попыток
                        messages = [
                            *messages[:2],
                            {'role': 'assistant', 'content': content[:6000]},
                            {'role': 'user', 'content': f'Ответ не прошёл проверку схемы: {str(exc)[:800]}. Верни только исправленный JSON.'},
                        ]
                except _TRANSIENT as exc:  # сеть, таймаут, 429, 5xx, авторизация
                    last_error = exc
                    code = getattr(exc, 'status_code', None)
                    self.status[role] = {'model': model, 'ok': False, 'error': type(exc).__name__, 'status': code}
                    logger.warning('llm error skill=%s model=%s status=%s type=%s attempt=%d/%d: %s',
                                   skill, model, code, type(exc).__name__, attempt + 1, attempts, str(exc)[:200])
                    if code in (401, 403):
                        break
                    if is_daily_limit(exc):
                        # Лимит общий для всех моделей шлюза: повторы и резерв только тянут время
                        self._mark_limit()
                        raise LLMUnavailable(LIMIT_MSG) from exc
                    if code == 429:
                        # Шлюз перегружен: пауза нарастает (15, 30, 45 с), иначе повторы тоже получают 429
                        await asyncio.sleep(15.0 * (attempt + 1))
                if attempt < attempts - 1:
                    await asyncio.sleep(_RETRY_PAUSES[attempt])
        if partial and (got := salvage()) is not None:
            return got
        raise LLMUnavailable(f'{skill}: модель не ответила ({type(last_error).__name__}: {str(last_error)[:200]})')

    async def embed(self, texts: list[str], stats: CallStats | None = None) -> list[list[float]]:
        """Векторы текстов моделью эмбеддингов шлюза (база знаний организации, FR-09).

        Каждая пачка — с таймаутом и теми же повторами, что у complete_json (паузы 1 и 3 с, при 429 —
        15, 30 с); 401/403 и суточный лимит — без повторов. Наружу — только LLMUnavailable.
        """
        if not self.enabled:
            raise LLMUnavailable('LLM не настроен')
        if self.limit_reached():
            raise LLMUnavailable(LIMIT_MSG)
        out: list[list[float]] = []
        attempts = len(_RETRY_PAUSES) + 1
        for i in range(0, len(texts), 16):
            batch = texts[i : i + 16]
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    async with self._sem:
                        resp = await asyncio.wait_for(
                            self._get().embeddings.create(model=self.settings.llm_model_embed, input=batch),
                            timeout=self.settings.llm_timeout_s,
                        )
                    vectors = [list(d.embedding) for d in resp.data]
                    break
                except (AttributeError, TypeError) as exc:
                    last_error = GatewayError(f'Ответ шлюза без data: {type(exc).__name__}')
                except _TRANSIENT as exc:
                    last_error = exc
                    code = getattr(exc, 'status_code', None)
                    logger.warning('llm embed error status=%s type=%s attempt=%d/%d', code, type(exc).__name__, attempt + 1, attempts)
                    if code in (401, 403):
                        raise LLMUnavailable(f'embed: шлюз отклонил ключ (HTTP {code})') from exc
                    if is_daily_limit(exc):
                        self._mark_limit()
                        raise LLMUnavailable(LIMIT_MSG) from exc
                    if code == 429:
                        await asyncio.sleep(15.0 * (attempt + 1))
                if attempt < attempts - 1:
                    await asyncio.sleep(_RETRY_PAUSES[attempt])
            else:
                raise LLMUnavailable(f'embed: модель не ответила ({type(last_error).__name__}: {str(last_error)[:200]})')
            out += vectors
            if stats is not None:
                stats.add('embed', int(getattr(getattr(resp, 'usage', None), 'prompt_tokens', 0) or 0), 0, 0.0)
        return out

    async def ping(self) -> dict[str, Any]:
        """Проверочный запрос для GET /api/v1/llm/status (одна попытка, таймаут не больше 30 с)."""
        if not self.enabled:
            return {'enabled': False, 'provider': self.settings.llm_providers}
        started = time.monotonic()
        try:
            # F15: проверочный запрос идёт через общий семафор, как и рабочие вызовы,
            # чтобы частые проверки статуса не обходили ограничение параллельности
            async with self._sem:
                resp = await asyncio.wait_for(
                    self._get().chat.completions.create(
                        model=self.settings.llm_model_generate,
                        messages=[{'role': 'user', 'content': 'Ответь одним словом: ок'}],
                        max_tokens=5,
                    ),
                    timeout=min(30.0, self.settings.llm_timeout_s),
                )
            if self._limit_day:
                self._limit_day = ''  # шлюз снова отвечает: лимит сброшен раньше полуночи
                self._save_spend()
            return {
                'enabled': True,
                'ok': bool(getattr(resp, 'choices', None)),
                'model': self.settings.llm_model_generate,
                'latency_s': round(time.monotonic() - started, 2),
            }
        except _TRANSIENT as exc:
            if is_daily_limit(exc):
                self._mark_limit()
            return {'enabled': True, 'ok': False, 'error': type(exc).__name__, 'daily_limit_reached': self.limit_reached()}


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
