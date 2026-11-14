import math
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: Literal["local", "production"] = "local"
    database_path: str = "data/lazy-capitalist.db"
    api_token: SecretStr | None = None
    youtube_enabled: bool = False
    youtube_token_key: SecretStr | None = None
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr | None = None
    youtube_redirect_uri: str = ""
    ai_provider: Literal["mock", "openai"] = "mock"
    allow_paid_ai: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    # USD, independently configured; CHF conversion is deliberately not implied.
    job_budget_usd: float = 0
    daily_budget_usd: float = 0
    monthly_budget_usd: float = 0
    lifetime_budget_usd: float = 0
    request_reservation_usd: float = 0
    input_usd_per_million: float = 0
    output_usd_per_million: float = 0

    @model_validator(mode="after")
    def validate_environment(self):
        values = (
            self.job_budget_usd,
            self.daily_budget_usd,
            self.monthly_budget_usd,
            self.lifetime_budget_usd,
            self.request_reservation_usd,
            self.input_usd_per_million,
            self.output_usd_per_million,
        )
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Budgets and rates must be finite and nonnegative")
        if self.environment == "production":
            if self.api_token is None or len(self.api_token.get_secret_value()) < 32:
                raise ValueError("Production requires an API_TOKEN of at least 32 characters")
        if self.ai_provider == "openai":
            if not self.allow_paid_ai or not self.openai_api_key:
                raise ValueError("OpenAI requires explicit paid AI enablement and a key")
            if any(v <= 0 for v in values):
                raise ValueError("OpenAI requires positive budgets, reservation and verified rates")
        return self
