from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Compose and the API share an env file. Compose-only keys (ports, database
    # bootstrap settings) must not prevent the API or migrations from starting.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    fireflint_base_url: str = ""
    flintplate_connector_key: str = ""
    flintplate_replacement_worker: bool = False

    # App
    app_env: str = "development"
    app_version: str = "0.1.0"
    # pydantic-settings v2: list fields require JSON array in env var
    # e.g. ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:3001"]
    # Default matches docker-compose.yml's HIREOS_FRONTEND_PORT default (3001).
    allowed_origins: list[str] = ["http://localhost:3001", "http://127.0.0.1:3001"]

    # Database
    database_url: str = "postgresql+asyncpg://hireos:hireos_secret@db:5432/hireos"

    # Redis
    redis_url: str = "redis://:redis_secret@redis:6379/0"

    # Optional OpenAI-compatible Chat Completions provider
    openai_api_key: str | None = None
    openai_base_url: str | None = None  # OpenAI-compatible provider URL, including local inference
    openai_model: str = "gpt-4o-mini"

    # Monitoring (Sprint 0.8)
    sentry_dsn: str | None = None
    frontend_url: str = "http://localhost:3001"
    invoice_validator_url: str = ""

    # Rate limiting (Sprint 0.8) – requests per minute per IP
    rate_limit_per_minute: int = 60

    # Job Scraper import key (shared secret, not user auth)
    scraper_import_key: str = "scraper-import-key-change-me"

    # Email / SMTP (Sprint 1.1 – optional, leave blank to disable)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@palmscout.invalid"
    smtp_tls: bool = True

    # Google Maps (Sprint MVP-2 – Map View)
    google_maps_api_key: str | None = None

    # ── Dev / AI-Throttle ─────────────────────────────────────────────────────
    # AI_MOCK_MODE=true        → LLM-Calls überspringen, Mock-Texte zurückgeben
    # AI_MAX_TOKENS=500        → Token-Limit pro Request (Kostensparen in Dev)
    # AI_REQUESTS_PER_MIN=5   → Max. LLM-Calls pro Minute (0 = unbegrenzt)
    ai_mock_mode: bool = False
    agents_external_ai_enabled: bool = False
    ai_max_tokens: int = 1500
    ai_requests_per_min: int = 20

    # Bundesagentur für Arbeit API (Sprint 2.5 – anonymous creds used if not set)
    ba_client_id: str | None = None
    ba_client_secret: str | None = None

    # S3 / Cloudflare R2 Storage (Sprint 2.8 – optional, leave blank to disable)
    s3_endpoint_url: str | None = None  # e.g. "https://<account>.r2.cloudflarestorage.com"
    s3_bucket: str | None = None  # e.g. "palmscout-assets"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_public_url_base: str | None = (
        None  # e.g. "https://assets.palmscout.invalid" (CDN/public URL)
    )

    # Stripe Billing (Sprint 2.3 – optional, leave blank to disable)
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_starter: str | None = None  # e.g. price_xxx
    stripe_price_professional: str | None = None
    stripe_price_enterprise: str | None = None

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
