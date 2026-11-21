import asyncio
from decimal import Decimal
import httpx
import pytest
from collections_agent.limits import Guards, LimitError, validate_input
from collections_agent.models import SessionState
from collections_agent.settings import Settings


class AtomicTestStore:
    """Isolated accounting double; NOT a production Redis fallback or Redis proof."""
    def __init__(self):
        self.values = {}
        self.lock = asyncio.Lock()

    async def incrby(self, key, value):
        async with self.lock:
            self.values[key] = self.values.get(key, 0) + value
            return self.values[key]


@pytest.mark.asyncio
async def test_zero_budget_blocks_all_entrypoints_without_network():
    from collections_agent.provider import Provider
    attempted = []
    def reject(request):
        attempted.append(request.url)
        raise AssertionError("No network permitted")
    settings = Settings(_env_file=None)
    for scope in ("public-text", "public-voice", "initial-eval"):
        state = SessionState()
        guards = Guards(settings)
        provider = Provider(settings, state, guards, scope, httpx.MockTransport(reject))
        with pytest.raises(LimitError):
            await provider.before_request(httpx.Request("POST", "https://api.meta.ai/v1/responses", json={"max_output_tokens":1024}))
        with pytest.raises(LimitError):
            await guards.turn(state, "What is my balance?", scope)
        with pytest.raises(LimitError):
            await guards.voice_slot(state)
        await provider.close()
    assert attempted == []


@pytest.mark.asyncio
async def test_concurrent_reservations_never_admit_above_ceiling():
    settings = Settings(_env_file=None, model_api_key="test", public_text_budget_usd=Decimal("0.000100"), total_provider_budget_usd=Decimal("0.000100"))
    store = AtomicTestStore()
    guards = Guards(settings, store, prefix="test-only")
    async def attempt():
        try:
            await guards.reserve("public-text", 30)
            return 30
        except LimitError:
            return 0
    assert sum(await asyncio.gather(*(attempt() for _ in range(20)))) == 90
    assert max(store.values.values()) >= 100


@pytest.mark.parametrize("text", ["", "   ", "é" * 1001])
def test_input_bounds(text):
    with pytest.raises(LimitError):
        validate_input(text)


@pytest.mark.asyncio
async def test_token_and_step_exhaustion_blocks_generation():
    from collections_agent.provider import Provider
    calls = []
    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"input_tokens":6001})
    settings = Settings(_env_file=None, model_api_key="test", public_text_budget_usd=1, total_provider_budget_usd=1)
    s = SessionState()
    provider = Provider(settings, s, Guards(settings, AtomicTestStore()), transport=httpx.MockTransport(transport))
    request = httpx.Request("POST", "https://api.meta.ai/v1/responses", json={"max_output_tokens":1024,"input":"test"})
    with pytest.raises(LimitError):
        await provider.before_request(request)
    assert calls == ["/v1/responses/input_tokens"] and s.requests == 0
    s.requests = 6
    with pytest.raises(LimitError):
        await provider.before_request(request)
    assert len(calls) == 1
    await provider.close()


@pytest.mark.asyncio
async def test_persistent_quota_keys_and_weighted_debits(monkeypatch):
    import collections_agent.limits as limits
    counters = {}
    class Limiter:
        def __init__(self, redis, limiter, prefix):
            self.prefix = prefix
        async def limit(self, identifier, rate=1):
            key = (self.prefix, identifier)
            counters[key] = counters.get(key, 0) + rate
            return type("Result", (), {"allowed": counters[key] <= 6})()
    monkeypatch.setattr(limits, "Ratelimit", Limiter)
    settings = Settings(_env_file=None, model_api_key="test", public_text_budget_usd=1, total_provider_budget_usd=1)
    for _ in range(6):
        await Guards(settings, AtomicTestStore()).turn(SessionState(visitor_id="same"), "Invoice", "public-text")
    with pytest.raises(LimitError):
        await Guards(settings, AtomicTestStore()).turn(SessionState(visitor_id="same"), "Invoice", "public-text")
    assert counters[("collections:turns:visitor-minute", "same")] == 7


@pytest.mark.asyncio
async def test_missing_store_fails_closed():
    s = Settings(_env_file=None, model_api_key="test", public_text_budget_usd=1, total_provider_budget_usd=1)
    with pytest.raises(LimitError, match="Quota store"):
        await Guards(s).turn(SessionState(), "Invoice", "public-text")
