"""Конфигурация приложения через pydantic-settings."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Настройки приложения. Секреты читаются только из окружения или .env."""

    model_config = SettingsConfigDict(
        env_file=('.env', '/opt/hackathon/ai.env'),
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    # --- Общие ---
    environment: str = 'development'
    log_level: str = 'INFO'
    app_name: str = 'МетодАгент'
    app_version: str = '0.1.0'
    api_v1_prefix: str = '/api/v1'
    docs_enabled: bool = True

    # --- Хранилище ---
    data_dir: Path = ROOT_DIR / 'data' / 'runtime'
    database_url: str = ''
    max_file_size_mb: int = 20
    max_files_per_request: int = 5

    # --- Auth ---
    secret_key: str = 'dev-secret-change-me'
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 60 * 12

    # --- LLM: OpenAI-совместимый шлюз (Cloud.ru Evolution / шлюз хакатона) ---
    llm_api_key: str = Field(
        default='',
        validation_alias=AliasChoices('LLM_API_KEY', 'CLOUDRU_API_KEY', 'OPENAI_API_KEY'),
    )
    llm_base_url: str = Field(
        default='https://foundation-models.api.cloud.ru/v1',
        validation_alias=AliasChoices('LLM_BASE_URL', 'CLOUDRU_BASE_URL', 'OPENAI_BASE_URL'),
    )
    llm_model_generate: str = 'GigaChat/GigaChat-3-Pro'
    llm_model_judge: str = 'ai-sage/GigaChat3.5-432B-A28B-Reasoning'
    llm_model_reserve: str = 'GigaChat/GigaChat-3-Pro'
    llm_model_embed: str = 'ai-sage/Giga-Embeddings-instruct-3B'
    llm_concurrency: int = 2  # шлюз хакатона: не больше 2 параллельных запросов
    llm_timeout_s: float = 120.0
    # cloudru — рабочий режим; fixtures — без сети, детерминированные ответы навыков
    llm_providers: str = 'cloudru'
    # Судья тратит токены рассуждающей модели: включается явно
    llm_judge_enabled: bool = True
    # Тарифы, ₽ за 1 млн токенов (вход, выход) — для отчёта о стоимости
    llm_price_in_rub: float = 73.03
    llm_price_out_rub: float = 176.39
    llm_judge_price_in_rub: float = 96.22
    llm_judge_price_out_rub: float = 288.60
    # Дневной бюджет шлюза хакатона 100 ₽: после порога навыки уходят в резервную генерацию
    llm_daily_budget_rub: float = 90.0
    # FR-30: модули генерируются параллельно (не меньше 4 потоков); к шлюзу одновременно идут не больше llm_concurrency запросов
    gen_workers: int = 6
    # Анонимный доступ (роль api) — только автопрогон POST /programs?mode=auto, с ограничением частоты на IP
    anon_runs_per_hour: int = 12

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == 'production'

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f'sqlite+aiosqlite:///{self.data_dir / "metodagent.db"}'

    @property
    def llm_enabled(self) -> bool:
        return self.llm_providers == 'cloudru' and bool(self.llm_api_key)

    @model_validator(mode='after')
    def validate_secret_key(self) -> Settings:
        """Слабый ключ в production останавливает запуск."""
        if 'change-me' in self.secret_key and self.is_production:
            msg = 'SECRET_KEY не задан: сгенерируйте python -c "import secrets; print(secrets.token_hex(32))"'
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Фабрика настроек (кэшируется)."""
    return Settings()
