"""Opt-in actual Redis proof. Never touches campaign/production counters."""
import asyncio
from uuid import uuid4
import pytest
from collections_agent.settings import Settings
from collections_agent.limits import Guards, LimitError, redis_client


@pytest.mark.asyncio
async def test_live_atomic_reservations():
    settings = Settings()
    if not settings.upstash_redis_rest_url or not settings.upstash_redis_rest_token:
        pytest.skip("Actual Redis verification requires free Upstash credentials")
    settings.model_api_key = "accounting-only-no-provider"
    settings.public_text_budget_usd = settings.total_provider_budget_usd = 1
    settings.budget_campaign_id = uuid4().hex
    redis = redis_client(settings)
    prefix = "collections-test-" + uuid4().hex
    guards = Guards(settings, redis, prefix=prefix)
    keys = [f"{prefix}:budget:{settings.budget_campaign_id}:{scope}" for scope in ("public-text", "total")]
    # Pre-create expiring test counters: no immortal test keys even after interruption.
    for key in keys:
        await redis.set(key, 0, ex=300)
    async def reserve():
        try:
            await guards.reserve("public-text", 300000)
            return 300000
        except LimitError:
            return 0
    amounts = await asyncio.gather(*(reserve() for _ in range(10)))
    assert sum(amounts) == 900000
    assert int(await redis.get(keys[1])) <= 1000000
