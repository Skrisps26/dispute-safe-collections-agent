import json
from math import ceil
import httpx
from openai import AsyncOpenAI
from livekit.plugins import openai
from .limits import Guards, LimitError, require_budget


class Provider:
    """One guarded SDK client per session; preflight never shares a hooked transport."""
    def __init__(self, settings, state, guards: Guards, scope="public-text", transport=None):
        self.settings, self.state, self.guards, self.scope = settings, state, guards, scope
        self.counter = httpx.AsyncClient(base_url=settings.meta_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {settings.model_api_key}"}, transport=transport, timeout=30)
        self.http = httpx.AsyncClient(event_hooks={"request":[self.before_request]}, transport=transport, timeout=30)
        self.client = AsyncOpenAI(api_key=settings.model_api_key or "disabled-no-key",
            base_url=settings.meta_base_url, max_retries=0, http_client=self.http)
        self.llm = openai.responses.LLM(model=settings.meta_model, base_url=settings.meta_base_url,
            client=self.client, use_websocket=False, reasoning={"effort":"minimal"}, store=False,
            max_output_tokens=1024, parallel_tool_calls=False, prompt_cache_breakpoints=False)

    async def before_request(self, request: httpx.Request):
        require_budget(self.settings, self.scope)  # before counting, including SDK prewarm
        if request.url.path.rstrip("/") != "/v1/responses":
            raise LimitError("Only guarded Responses generation is permitted.")
        body = json.loads(request.content)
        is_judge = self.scope == "initial-eval" and body.get("reasoning", {}).get("effort") == "high"
        input_cap, output_cap = (16000,4096) if is_judge else (6000,1024)
        output = body.get("max_output_tokens", 0)
        if not 0 < output <= output_cap or self.state.requests >= (1 if is_judge else 6):
            raise LimitError("Generation step/output limit reached.")
        count_body = {k:v for k,v in body.items() if k in {"model","input","instructions","tools","tool_choice","text","reasoning","parallel_tool_calls"}}
        count_body["stream"] = False
        response = await self.counter.post("responses/input_tokens", json=count_body)
        response.raise_for_status()
        tokens = response.json().get("input_tokens")
        if type(tokens) is not int or tokens < 0 or tokens > input_cap:
            raise LimitError("History exceeds the input limit or token count is unavailable. Start a new demo.")
        reserved_tokens = tokens + output
        if not is_judge and self.state.reserved_tokens + reserved_tokens > 24000:
            raise LimitError("Per-turn token reservation limit reached.")
        await self.guards.reserve(self.scope, ceil(tokens * 1.25 + output * 4.25))
        self.state.requests += 1
        self.state.reserved_tokens += reserved_tokens

    async def close(self):
        await self.client.close()
        await self.counter.aclose()
