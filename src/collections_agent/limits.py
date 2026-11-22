from decimal import Decimal
from upstash_redis.asyncio import Redis
from upstash_ratelimit import FixedWindow
from upstash_ratelimit.asyncio import Ratelimit
from .settings import Settings


class LimitError(RuntimeError):
    pass


def redis_client(settings: Settings) -> Redis:
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        raise LimitError("Quota store unavailable; the demo is closed.")
    return Redis(url=settings.upstash_redis_rest_url, token=settings.upstash_redis_rest_token, retries=0)


def require_budget(settings: Settings, scope: str) -> None:
    if settings.ceiling(scope) <= 0 or settings.total_provider_budget_usd <= 0:
        raise LimitError("Provider calls disabled: approved budget is zero.")
    if not settings.model_api_key:
        raise LimitError("Provider calls disabled: MODEL_API_KEY is unavailable.")


def validate_input(text: str) -> None:
    if not text.strip() or len(text.encode("utf-8")) > 2000:
        raise LimitError("Enter between 1 and 2000 UTF-8 bytes.")


class Guards:
    def __init__(self, settings: Settings, redis=None, prefix="collections"):
        self.settings, self._redis, self.prefix = settings, redis, prefix

    @property
    def redis(self):
        if self._redis is None:
            self._redis = redis_client(self.settings)
        return self._redis

    async def turn(self, state, text: str, scope: str) -> None:
        validate_input(text)
        require_budget(self.settings, scope)
        if len(state.customer_turns) >= 30:
            raise LimitError("Session turn limit reached. Start an explicitly new demo.")
        if len(state.events) > 460:
            raise LimitError("Evidence capacity reached. Start an explicitly new demo.")
        for label, identifier, cap, seconds in [
            ("visitor-minute",state.visitor_id,6,60), ("visitor-day",state.visitor_id,30,86400),
            ("ip-day",state.ip_hash,60,86400), ("global-day","all",200,86400)]:
            response = await Ratelimit(redis=self.redis, limiter=FixedWindow(max_requests=cap, window=seconds),
                prefix=f"{self.prefix}:turns:{label}").limit(identifier, rate=1)
            if not response.allowed:
                raise LimitError("Fixed-period visitor quota exceeded. Try a later period.")

    async def reserve(self, scope: str, microdollars: int) -> None:
        require_budget(self.settings, scope)
        if microdollars <= 0:
            raise LimitError("Invalid reservation")
        ceilings = [(scope, self.settings.ceiling(scope)),
                    ("total",int(self.settings.total_provider_budget_usd * Decimal(1_000_000)))]
        for name, ceiling in ceilings:
            key = f"{self.prefix}:budget:{self.settings.budget_campaign_id}:{name}"
            used = await self.redis.incrby(key, microdollars)
            if used > ceiling:
                raise LimitError("Lifetime provider budget exhausted; reservations are not refunded.")

    async def voice_slot(self, state) -> None:
        s = self.settings
        require_budget(s, "public-voice")
        if not s.voice_enabled or not s.gnani_api_key or s.gnani_max_cost_per_call_usd <= 0:
            raise LimitError("Voice disabled: verified speech pricing/credit safeguards required.")
        for label, key, cap in [("visitor",state.visitor_id,300),("ip",state.ip_hash,600),("global","all",1800)]:
            response = await Ratelimit(redis=self.redis, limiter=FixedWindow(max_requests=cap, window=86400),
                prefix=f"{self.prefix}:voice:{label}").limit(key, rate=150)
            if not response.allowed:
                raise LimitError("Fixed-period voice allowance exhausted.")
        from math import ceil
        await self.reserve("public-voice", ceil(s.gnani_max_cost_per_call_usd * 1_000_000))
