"""HTTP-клиент Cloud.ru Evolution Foundation Models (ТЗ, раздел 4).

Обращается к шлюзу Cloud.ru (или шлюзу хакатона на его основе) напрямую через httpx:
`POST {base_url}/chat/completions` и `POST {base_url}/embeddings`. Сторонних SDK нет.
Повторы делает LLMClient: здесь один запрос — одна попытка.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx


class GatewayError(Exception):
    """Ошибка шлюза: HTTP-статус (None — сеть или таймаут) и тело ответа."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = '') -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _ns(data: Any) -> Any:
    """JSON → объекты с атрибутами (resp.choices[0].message.content)."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_ns(x) for x in data]
    return data


class _Endpoint:
    def __init__(self, gw: CloudRuGateway, path: str) -> None:
        self._gw, self._path = gw, path

    async def create(self, **payload: Any) -> Any:
        return await self._gw.post(self._path, payload)


class _Chat:
    def __init__(self, gw: CloudRuGateway) -> None:
        self.completions = _Endpoint(gw, '/chat/completions')


class CloudRuGateway:
    """Клиент шлюза: `chat.completions.create(...)` и `embeddings.create(...)`."""

    max_retries = 0  # повторы и резервная модель — в LLMClient

    def __init__(self, base_url: str, api_key: str, timeout: float) -> None:
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        )
        self.chat = _Chat(self)
        self.embeddings = _Endpoint(self, '/embeddings')

    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        try:
            r = await self._http.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise GatewayError(f'Таймаут шлюза {self.timeout:.0f} с: {type(exc).__name__}') from exc
        except httpx.HTTPError as exc:
            raise GatewayError(f'Шлюз недоступен: {type(exc).__name__}') from exc
        if r.status_code >= 400:
            try:
                body: Any = r.json()
            except ValueError:
                body = r.text[:2000]
            raise GatewayError(f'HTTP {r.status_code} от шлюза', r.status_code, body)
        try:
            return _ns(r.json())
        except ValueError as exc:
            raise GatewayError('Шлюз вернул не JSON', r.status_code, r.text[:2000]) from exc

    async def aclose(self) -> None:
        await self._http.aclose()
