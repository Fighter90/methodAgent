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
    # ТЗ, 4.11: токен доступа живёт 30 минут, токен обновления — 30 дней (POST /auth/refresh)
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    # Срок токена API, который выдаёт администратор (POST /admin/api-tokens), если срок не указан; не больше 365 дней
    api_token_default_days: int = 90

    # --- LLM: только Cloud.ru Evolution Foundation Models (напрямую или через шлюз хакатона) ---
    llm_api_key: str = Field(
        default='',
        validation_alias=AliasChoices('LLM_API_KEY', 'CLOUDRU_API_KEY'),
    )
    llm_base_url: str = Field(
        default='https://foundation-models.api.cloud.ru/v1',
        validation_alias=AliasChoices('LLM_BASE_URL', 'CLOUDRU_BASE_URL'),
    )
    llm_model_generate: str = 'GigaChat/GigaChat-3-Pro'
    llm_model_judge: str = 'ai-sage/GigaChat3.5-432B-A28B-Reasoning'
    llm_model_reserve: str = 'GigaChat/GigaChat-3-Pro'
    llm_model_embed: str = 'ai-sage/Giga-Embeddings-instruct-3B'
    # Зарезервировано (таблица 26 ТЗ): реранкера в текущей сборке нет, значение читается, но не используется
    llm_model_rerank: str = ''
    llm_concurrency: int = 2  # шлюз хакатона: не больше 2 параллельных запросов
    llm_timeout_s: float = 120.0
    # cloudru — рабочий режим; fixtures — без сети, детерминированные ответы навыков
    llm_providers: str = 'cloudru'
    # Судья тратит токены рассуждающей модели; отключается LLM_JUDGE_ENABLED=false или в админке
    llm_judge_enabled: bool = True
    # Подробные слайды лекций вторым вызовом на лекцию (SPEC-CONTENT-16); LLM_SLIDES_DETAIL=false или админка — только слайды модуля
    llm_slides_detail: bool = True
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
    # ТЗ, 4.11 «Меры безопасности»: вход — не больше 5 неудачных попыток в минуту с адреса, дальше 429
    login_failures_per_minute: int = 5
    # ТЗ, 4.11: не больше 30 новых программ в час на пользователя; для роли api — свой лимит профиля
    programs_per_hour: int = 30
    api_programs_per_hour: int = 30
    max_parallel_jobs: int = 4  # больше одновременных заданий ВМ 2 ядра / 4 ГБ не тянет (429)
    # Зарезервировано (таблица 26 ТЗ): очередь заданий встроенная (asyncio), Redis и arq не подключены
    redis_url: str = ''

    # --- Песочница примеров кода (V-24): лимит времени и памяти дочернего процесса ---
    sandbox_timeout_s: int = 10
    sandbox_memory_mb: int = 512

    # --- Вход и регистрация (администратор меняет на странице «Администрирование») ---
    registration_enabled: bool = True
    # Новый пользователь получает минимальные права: эксперт без назначенных модулей ничего чужого не видит
    registration_default_role: str = 'expert'
    demo_accounts_enabled: bool = True
    # SSO предусмотрен, но не подключён: параметры хранятся, кнопка на форме входа помечена «скоро»
    sso_enabled: bool = False
    sso_provider: str = 'oidc'
    sso_display_name: str = 'Единый вход организации'
    sso_issuer_url: str = ''
    sso_client_id: str = ''
    sso_client_secret: str = ''
    # Пароль почты для уведомлений (FR-59); хост и отправитель — в профиле организации
    smtp_password: str = ''

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
        """Пустой или учебный SECRET_KEY заменяется случайным ключом из data_dir: токены и секреты не подписываются известной строкой."""
        if len(self.secret_key) < 16 or 'change-me' in self.secret_key:
            import secrets

            f = self.data_dir / '.secret_key'
            try:
                if not f.exists():
                    self.data_dir.mkdir(parents=True, exist_ok=True)
                    f.write_text(secrets.token_hex(32), encoding='utf-8')
                    f.chmod(0o600)
                self.secret_key = f.read_text(encoding='utf-8').strip()
            except OSError:
                if self.is_production:
                    raise ValueError('SECRET_KEY не задан, и data_dir недоступен для записи ключа') from None
        return self


@lru_cache
def get_settings() -> Settings:
    """Фабрика настроек (кэшируется)."""
    return Settings()
