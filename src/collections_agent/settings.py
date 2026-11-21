from decimal import Decimal
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    model_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    meta_model: Literal["muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.3"] = "muse-spark-1.3"
    prompt_version: Literal["v1", "v2"] = "v2"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    gnani_api_key: str = ""
    voice_enabled: bool = False
    gnani_max_cost_per_call_usd: Decimal = Decimal(0)
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    initial_eval_budget_usd: Decimal = Decimal(0)
    public_text_budget_usd: Decimal = Decimal(0)
    public_voice_budget_usd: Decimal = Decimal(0)
    total_provider_budget_usd: Decimal = Decimal(0)
    budget_campaign_id: str = "demo-v1"

    def ceiling(self, scope: str) -> int:
        value = {"initial-eval": self.initial_eval_budget_usd,
                 "public-text": self.public_text_budget_usd,
                 "public-voice": self.public_voice_budget_usd}[scope]
        return max(0, int(value * 1_000_000))
