"""Слой моделей: OpenAI-совместимый клиент Cloud.ru / шлюза хакатона (ТЗ, 4.11).

Правила:
- повтор до 2 раз при ошибке, HTTP 429/5xx или невалидном JSON (паузы 1 и 3 с),
  затем резервная модель той же роли; при ошибке авторизации — сразу резерв;
- параллельность ограничена семафором, после 429 временно снижается;
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
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', cleaned, flags=re.S)
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
        self._judge_sem = asyncio.Semaphore(4)
        self.status: dict[str, Any] = {}

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
        sem = self._judge_sem if role == 'judge' else self._sem
        last_error: Exception | None = None
        for model in self._models(role):
            messages: list[dict[str, str]] = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
            for attempt in range(len(_RETRY_PAUSES) + 1):
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
                    # Модель получает текст ошибки и исправляет ответ — это одна из попыток
                    messages = [
                        *messages[:2],
                        {'role': 'assistant', 'content': (content or '')[:6000]},
                        {'role': 'user', 'content': f'Ответ не прошёл проверку схемы: {str(exc)[:800]}. Верни только исправленный JSON.'},
                    ]
                except Exception as exc:  # noqa: BLE001 — сеть, 429, 5xx, авторизация
                    last_error = exc
                    code = getattr(exc, 'status_code', None)
                    self.status[role] = {'model': model, 'ok': False, 'error': type(exc).__name__, 'status': code}
                    logger.warning('llm error skill=%s model=%s status=%s type=%s', skill, model, code, type(exc).__name__)
                    if code in (401, 403):
                        break
                    if code == 429:
                        await asyncio.sleep(_RETRY_PAUSES[-1])
                if attempt < len(_RETRY_PAUSES):
                    await asyncio.sleep(_RETRY_PAUSES[attempt])
        raise LLMUnavailable(f'{skill}: модель не ответила ({type(last_error).__name__})')

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
            return {
                'enabled': True,
                'ok': bool(resp.choices),
                'model': self.settings.llm_model_generate,
                'latency_s': round(time.monotonic() - started, 2),
            }
        except Exception as exc:  # noqa: BLE001
            return {'enabled': True, 'ok': False, 'error': type(exc).__name__}


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
