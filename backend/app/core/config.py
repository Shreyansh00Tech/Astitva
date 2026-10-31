from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = "ASTITVA"
    app_env: str = "development"  # development | test | production
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/astitva"
    redis_url: str = "redis://localhost:6379/0"

    # Secrets: MUST be overridden in production via environment variables.
    jwt_secret: str = "dev-only-change-me-astitva-jwt-secret-0000000000"
    token_pepper: str = "dev-only-change-me-astitva-pepper"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 7
    mfa_challenge_ttl_seconds: int = 300
    otp_ttl_seconds: int = 600

    cookie_secure: bool = False  # True in production (HTTPS)
    cookie_samesite: str = "strict"
    cookie_domain: str | None = None

    # Brute-force controls
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900
    lockout_base_seconds: int = 60
    lockout_max_seconds: int = 1800
    ip_bucket_capacity: int = 20
    ip_bucket_refill_per_sec: float = 20 / 60
    account_bucket_capacity: int = 10
    account_bucket_refill_per_sec: float = 10 / 300
    stuffing_distinct_accounts_threshold: int = 8

    # Governance
    recertification_interval_days: int = 30
    recertification_due_days: int = 7
    breakglass_default_minutes: int = 60
    breakglass_max_minutes: int = 240
    expiring_soon_hours: int = 24

    # AI provider: "none" (rule engine only), "anthropic", or "openai" (any OpenAI-compatible endpoint)
    llm_provider: str = "none"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str | None = None

    cors_origins: str = "http://localhost:3000"
    enable_inprocess_scheduler: bool = True
    expose_dev_outbox: bool = True  # shows simulated emails/SMS in development only

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        if s.jwt_secret.startswith("dev-only") or s.token_pepper.startswith("dev-only"):
            raise RuntimeError("Refusing to start in production with development secrets")
        s.cookie_secure = True
        s.expose_dev_outbox = False
    return s
