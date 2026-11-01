import hashlib
import hmac
import os
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

    # NamoID Hosted Auth (OpenID Connect, Authorization Code + PKCE S256).
    # Issuer and Client ID come from the NamoID Console. The Client Secret is optional
    # (public client with PKCE when empty) and must only ever live in the local .env.
    # Public (non-secret) values of the sandbox app, so sign-in works without a .env.
    namoid_issuer: str = "https://astitva-0efc7e.sandbox.namoid.in"
    namoid_client_id: str = "namoid_client_test_o2cLBiO3v9pcfKb2os5nn4ORagvF5RdI"
    namoid_client_secret: str = ""
    namoid_redirect_uri: str = "http://localhost:8000/api/auth/namoid/callback"
    namoid_scopes: str = "openid profile email"
    # Optional demo mapping "namoid-email=astitva-email,..." to sign in as a seeded persona
    namoid_user_map: str = ""
    # Unknown NamoID users are created as Employees (Security Manager assigns other roles)
    namoid_auto_provision: bool = True
    # Roles from NamoID: when the ID token / userinfo carries roles, they become the user's
    # ASTITVA roles at every sign-in. NAMOID_ROLES_CLAIM pins the claim (dotted path) if needed.
    namoid_role_sync: bool = True
    namoid_roles_claim: str = ""
    frontend_url: str = "http://localhost:3000"

    cors_origins: str = "http://localhost:3000"
    enable_inprocess_scheduler: bool = True
    # Serverless hosts (Vercel) have no long-running scheduler: the periodic jobs run at most once per
    # interval on the back of normal API traffic instead (see app.main.request_ticks).
    enable_request_ticks: bool = False
    # Vercel: migrate + seed on the first request of a new instance (advisory-locked, cheap when done).
    auto_setup: bool = False
    seed_mode: str = "clean"  # clean (only the 5 people) | demo (with history) | none
    expose_dev_outbox: bool = True  # shows simulated emails/SMS in development only

    @property
    def namoid_enabled(self) -> bool:
        return bool(self.namoid_issuer and self.namoid_client_id)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _normalize_db_url(url: str) -> str:
    # Neon / Vercel Postgres hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _find_env(names: tuple[str, ...], suffixes: tuple[str, ...]) -> str | None:
    """Vercel storage integrations may add a custom prefix (e.g. STORAGE_DATABASE_URL). Exact names win."""
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    for k in sorted(os.environ):
        if k.endswith(suffixes) and "UNPOOLED" not in k and "NON_POOLING" not in k and os.environ[k]:
            return os.environ[k]
    return None


def _apply_vercel_defaults(s: Settings) -> None:
    """One Vercel project serves the UI and /api on the same domain. Fill in what the platform already knows."""
    env = os.environ
    if "DATABASE_URL" not in env:
        alt = _find_env(("POSTGRES_URL", "NEON_DATABASE_URL"), ("_DATABASE_URL", "_POSTGRES_URL"))
        if alt:
            s.database_url = alt
    if "REDIS_URL" not in env:
        alt = _find_env(("KV_URL", "UPSTASH_REDIS_URL"), ("_REDIS_URL", "_KV_URL"))
        if alt:
            s.redis_url = alt
    host = env.get("VERCEL_PROJECT_PRODUCTION_URL") or env.get("VERCEL_URL")
    if host:
        origin = f"https://{host}"
        if "FRONTEND_URL" not in env:
            s.frontend_url = origin
        if "NAMOID_REDIRECT_URI" not in env:
            s.namoid_redirect_uri = f"{origin}/api/auth/namoid/callback"
        if "CORS_ORIGINS" not in env:
            s.cors_origins = origin
    # HTTPS everywhere on Vercel. APP_ENV stays "demo" (not "production") so the simulated inbox that shows
    # the demo accounts' sign-in codes keeps working; all data in this deployment is fictional.
    if "APP_ENV" not in env:
        s.app_env = "demo"
    if "COOKIE_SECURE" not in env:
        s.cookie_secure = True
    if "ENABLE_INPROCESS_SCHEDULER" not in env:
        s.enable_inprocess_scheduler = False
    if "ENABLE_REQUEST_TICKS" not in env:
        s.enable_request_ticks = True
    if "AUTO_SETUP" not in env:
        s.auto_setup = True
    # No JWT_SECRET / TOKEN_PEPPER set: derive them from the database URL, which is already a secret
    # that only this deployment holds. Setting both explicitly in Vercel is still the better choice.
    if "JWT_SECRET" not in env and "TOKEN_PEPPER" not in env:
        def derive(label: str) -> str:
            return hmac.new(s.database_url.encode(), f"astitva:{label}".encode(), hashlib.sha256).hexdigest()
        s.jwt_secret = derive("jwt")
        s.token_pepper = derive("pepper")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if os.environ.get("VERCEL"):
        _apply_vercel_defaults(s)
    s.database_url = _normalize_db_url(s.database_url)
    if s.is_production:
        if s.jwt_secret.startswith("dev-only") or s.token_pepper.startswith("dev-only"):
            raise RuntimeError("Refusing to start in production with development secrets")
        s.cookie_secure = True
        s.expose_dev_outbox = False
    return s
