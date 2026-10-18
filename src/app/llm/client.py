"""Слой моделей: OpenAI-совместимый клиент Cloud.ru / шлюза хакатона (ТЗ, 4.11).

Правила:
- повтор до 2 раз при ошибке, HTTP 5xx или невалидном JSON (паузы 1 и 3 с), при 429 — пауза 15, 30 с;
  затем резервная модель той же роли; при ошибке авторизации — сразу резерв;
- параллельность ограничена семафором, после 429 временно снижается;
- суточный лимит шлюза (429 «daily spending limit») — без повторов: до 00:00 МСК генерация по шаблонам;
- каждый вызов учитывает токены и рубли; ключ и тексты запросов не логируются.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

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


@dataclass
class CallStats:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0
    calls: int = 0
    by_skill: dict[str, dict[str, float]] = field(default_factory=dict)

    def add(self, skill: str, tin: int, tout: int, cost: float) -> None:
        self.tokens_in += tin
        self.tokens_out += tout
        self.cost_rub += cost
        self.calls += 1
        s = self.by_skill.setdefault(skill, {'tokens_in': 0, 'tokens_out': 0, 'cost_rub': 0.0, 'calls': 0})
        s['tokens_in'] += tin
        s['tokens_out'] += tout
        s['cost_rub'] = round(s['cost_rub'] + cost, 4)
        s['calls'] += 1


def parse_json(text: str) -> Any:
    """Снимает обрамление ```json, блоки рассуждений и лишние запятые, затем разбирает JSON."""
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
    return json.loads(cleaned)


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
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key,
                timeout=self.settings.llm_timeout_s,
                max_retries=0,
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
    ) -> Any:
        """Вызывает модель и возвращает JSON, проверенный Pydantic-схемой навыка."""
        if not self.enabled:
            raise LLMUnavailable('LLM не настроен')
        if self.limit_reached():
            raise LLMUnavailable(LIMIT_MSG)
        if self.spent_today() >= self.settings.llm_daily_budget_rub:
            raise LLMUnavailable(f'Дневной бюджет LLM {self.settings.llm_daily_budget_rub:.0f} ₽ исчерпан')
        sem = self._judge_sem if role == 'judge' else self._sem
        last_error: Exception | None = None
        for model in self._models(role):
            messages: list[dict[str, str]] = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
            # Ответ судьи дорогой и долгий (модель рассуждений): одна попытка, затем резервная модель
            attempts = 1 if model == self.settings.llm_model_judge else len(_RETRY_PAUSES) + 1
            for attempt in range(attempts):
                started = time.monotonic()
                try:
                    async with sem:
                        resp = await self._get().chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    content = resp.choices[0].message.content or ''
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
                except Exception as exc:  # noqa: BLE001 — сеть, 429, 5xx, авторизация
                    last_error = exc
                    code = getattr(exc, 'status_code', None)
                    self.status[role] = {'model': model, 'ok': False, 'error': type(exc).__name__, 'status': code}
                    logger.warning('llm error skill=%s model=%s status=%s type=%s', skill, model, code, type(exc).__name__)
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
        raise LLMUnavailable(f'{skill}: модель не ответила ({type(last_error).__name__})')

    async def embed(self, texts: list[str], stats: CallStats | None = None) -> list[list[float]]:
        """Векторы текстов моделью эмбеддингов шлюза (база знаний организации, FR-09)."""
        if not self.enabled:
            raise LLMUnavailable('LLM не настроен')
        if self.limit_reached():
            raise LLMUnavailable(LIMIT_MSG)
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):
            async with self._sem:
                resp = await self._get().embeddings.create(model=self.settings.llm_model_embed, input=texts[i : i + 16])
            out += [list(d.embedding) for d in resp.data]
            if stats is not None:
                stats.add('embed', int(getattr(getattr(resp, 'usage', None), 'prompt_tokens', 0) or 0), 0, 0.0)
        return out

    async def ping(self) -> dict[str, Any]:
        """Проверочный запрос для GET /api/v1/llm/status."""
        if not self.enabled:
            return {'enabled': False, 'provider': self.settings.llm_providers}
        started = time.monotonic()
        try:
            resp = await self._get().chat.completions.create(
                model=self.settings.llm_model_generate,
                messages=[{'role': 'user', 'content': 'Ответь одним словом: ок'}],
                max_tokens=5,
            )
            if self._limit_day:
                self._limit_day = ''  # шлюз снова отвечает: лимит сброшен раньше полуночи
                self._save_spend()
            return {
                'enabled': True,
                'ok': bool(resp.choices),
                'model': self.settings.llm_model_generate,
                'latency_s': round(time.monotonic() - started, 2),
            }
        except Exception as exc:  # noqa: BLE001
            if is_daily_limit(exc):
                self._mark_limit()
            return {'enabled': True, 'ok': False, 'error': type(exc).__name__, 'daily_limit_reached': self.limit_reached()}


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
