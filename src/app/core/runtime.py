"""Настройки, которые администратор меняет в интерфейсе без перезапуска (ключи, модели, лимиты, вход, SSO).

Значение из таблицы settings перекрывает переменную окружения; секреты хранятся зашифрованными
и наружу отдаются только маской. Удаление значения возвращает то, что задано окружением.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import SecretUnreadable, decrypt, encrypt, mask
from app.core.db import SettingRow, sessionmaker
from app.core.errors import BadRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    type: str  # str, secret, int, float, bool, choice
    hint: str = ''
    options: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None


FIELDS: tuple[Field, ...] = (
    Field('llm_providers', 'llm', 'Режим генерации', 'choice', 'cloudru — модель шлюза; fixtures — без сети, детерминированные ответы навыков', ('cloudru', 'fixtures')),
    Field('llm_base_url', 'llm', 'Адрес шлюза Cloud.ru Foundation Models', 'str', 'Например, https://foundation-models.api.cloud.ru/v1'),
    Field('llm_api_key', 'llm', 'Ключ API шлюза', 'secret', 'Хранится зашифрованным; показываются только последние символы'),
    Field('llm_model_generate', 'llm', 'Модель генерации', 'str'),
    Field('llm_model_judge', 'llm', 'Модель-судья (проверка по смыслу)', 'str'),
    Field('llm_model_reserve', 'llm', 'Резервная модель', 'str'),
    Field('llm_model_embed', 'llm', 'Модель эмбеддингов (поиск по базе знаний)', 'str'),
    Field('llm_judge_enabled', 'llm', 'Включить судью', 'bool', 'Судья тратит токены рассуждающей модели'),
    Field('llm_concurrency', 'limits', 'Одновременных запросов к шлюзу', 'int', 'Шлюз хакатона допускает 2', min=1, max=16),
    Field('gen_workers', 'limits', 'Потоков сборки модулей', 'int', 'FR-30: не меньше 4', min=1, max=32),
    Field('llm_timeout_s', 'limits', 'Таймаут запроса к модели, с', 'float', min=5, max=900),
    Field('llm_daily_budget_rub', 'limits', 'Дневной бюджет LLM, ₽', 'float', 'После порога навыки переходят на резервную генерацию', min=0, max=1_000_000),
    Field('max_parallel_jobs', 'limits', 'Одновременных заданий', 'int', min=1, max=64),
    Field('anon_runs_per_hour', 'limits', 'Автопрогонов без токена в час с одного адреса', 'int', min=0, max=10_000),
    Field('registration_enabled', 'auth', 'Открыта регистрация', 'bool'),
    Field('registration_default_role', 'auth', 'Роль нового пользователя', 'choice', 'Минимальные права — эксперт: видит только назначенные ему модули', ('expert', 'methodist', 'head')),
    Field('demo_accounts_enabled', 'auth', 'Демо-учётки на форме входа', 'bool', 'Выключите для работы с реальными пользователями. Учётка admin остаётся: смените ей пароль в разделе «Пользователи»'),
    Field('access_token_expire_minutes', 'auth', 'Срок жизни входа, мин', 'int', min=15, max=60 * 24 * 30),
    Field('sso_enabled', 'sso', 'Показывать вход через SSO', 'bool', 'Заготовка: параметры хранятся, подключение протокола — в следующей версии'),
    Field('sso_provider', 'sso', 'Протокол', 'choice', options=('oidc', 'saml')),
    Field('sso_display_name', 'sso', 'Название на кнопке', 'str'),
    Field('sso_issuer_url', 'sso', 'Issuer / адрес IdP', 'str', 'Например, https://sso.example.ru/realms/acr'),
    Field('sso_client_id', 'sso', 'Client ID', 'str'),
    Field('sso_client_secret', 'sso', 'Client secret', 'secret'),
    Field('smtp_password', 'mail', 'Пароль почты для уведомлений', 'secret', 'Сервер, порт, логин и отправитель — в профиле организации'),
)
BY_KEY = {f.key: f for f in FIELDS}
GROUPS = {'llm': 'Модель и ключи', 'limits': 'Лимиты и производительность', 'auth': 'Вход и регистрация', 'sso': 'Единый вход (SSO)', 'mail': 'Почта'}

_baseline: dict[str, Any] = {}
_overridden: set[str] = set()


def _coerce(f: Field, value: Any) -> Any:
    try:
        if f.type == 'bool':
            if isinstance(value, str):
                return value.lower() in ('1', 'true', 'да', 'on')
            return bool(value)
        if f.type == 'int':
            v: Any = int(value)
        elif f.type == 'float':
            v = float(value)
        else:
            v = str(value).strip()
    except (TypeError, ValueError):
        raise BadRequest(f'«{f.label}»: неверное значение', details={'key': f.key}) from None
    if f.type in ('int', 'float') and ((f.min is not None and v < f.min) or (f.max is not None and v > f.max)):
        raise BadRequest(f'«{f.label}»: допустимо от {f.min:g} до {f.max:g}', details={'key': f.key})
    if f.type == 'choice' and v not in f.options:
        raise BadRequest(f'«{f.label}»: одно из {", ".join(f.options)}', details={'key': f.key})
    return v


def _apply(key: str, value: Any) -> None:
    s = get_settings()
    _baseline.setdefault(key, getattr(s, key))
    setattr(s, key, value)


def _reset_clients() -> None:
    """Новый ключ, адрес или лимит шлюза действует со следующего запроса."""
    from app.llm import client

    client._client = None


async def load() -> None:
    """При старте: значения администратора поверх окружения."""
    async with sessionmaker()() as s:
        rows = (await s.execute(select(SettingRow))).scalars().all()
    for r in rows:
        f = BY_KEY.get(r.key)
        if f is None:
            continue
        value = r.value
        if f.type == 'secret':
            try:
                value = decrypt(value)
            except (SecretUnreadable, ValueError):
                logger.warning('Секрет %s не расшифрован (сменился SECRET_KEY?) — используется значение окружения', r.key)
                continue
        _apply(r.key, value)
        _overridden.add(r.key)
    _reset_clients()


def describe() -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    for f in FIELDS:
        value = getattr(s, f.key)
        source = 'admin' if f.key in _overridden else ('env' if value not in ('', None) else 'none')
        item: dict[str, Any] = {'key': f.key, 'group': f.group, 'group_title': GROUPS[f.group], 'label': f.label, 'type': f.type,
                                'hint': f.hint, 'options': list(f.options), 'min': f.min, 'max': f.max, 'source': source}
        if f.type == 'secret':
            item |= {'value': mask(value), 'set': bool(value)}
        else:
            item['value'] = value
        out.append(item)
    return out


async def update(values: dict[str, Any], clear: list[str], actor: str) -> list[str]:
    """Сохраняет изменения; пустое значение секрета означает «не менять», clear — вернуть значение окружения."""
    unknown = (set(values) | set(clear)) - set(BY_KEY)
    if unknown:
        raise BadRequest(f'Неизвестные настройки: {", ".join(sorted(unknown))}')
    changed: list[str] = []
    prepared: dict[str, Any] = {}
    for key, raw in values.items():
        f = BY_KEY[key]
        if f.type == 'secret' and (raw in (None, '') or str(raw).startswith('••••')):
            continue
        prepared[key] = _coerce(f, raw)
    async with sessionmaker()() as s:
        for key, v in prepared.items():
            stored = encrypt(v) if BY_KEY[key].type == 'secret' else v
            row = await s.get(SettingRow, key)
            if row is None:
                s.add(SettingRow(key=key, value=stored, updated_by=actor))
            else:
                row.value, row.updated_by = stored, actor
            changed.append(key)
        for key in clear:
            row = await s.get(SettingRow, key)
            if row is not None:
                await s.delete(row)
            changed.append(key)
        await s.commit()
    for key, v in prepared.items():
        _apply(key, v)
        _overridden.add(key)
    for key in clear:
        if key in _baseline:
            setattr(get_settings(), key, _baseline[key])
        _overridden.discard(key)
    if changed:
        _reset_clients()
    return changed
