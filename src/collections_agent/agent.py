import asyncio
from livekit.agents import Agent, RunContext, function_tool, llm
from .fixtures import ROOT
from .limits import LimitError
from .models import SessionState, new_id
from .replies import ReplyPlan, SAFE_ERROR, render
from .tools import DomainTools, Reason


class CollectionsAgent(Agent):
    def __init__(self, state: SessionState, provider):
        self.state, self.provider = state, provider
        self.domain = DomainTools(state)
        self._generation_lock = asyncio.Lock()
        self.voice = None
        super().__init__(instructions=(ROOT / f"prompts/{state.prompt_version}.md").read_text(),
                         llm=provider.llm, turn_detection="manual")

    @function_tool
    async def lookup_invoice(self, context: RunContext[SessionState], invoice_id: str | None = None):
        """Read the server-bound invoice and approved options; other IDs are denied."""
        return self.domain.execute("lookup_invoice", {"invoice_id":invoice_id}, call_id=context.function_call.call_id).model_dump(mode="json")

    @function_tool
    async def get_payment_history(self, context: RunContext[SessionState], invoice_id: str | None = None):
        """Read recorded payments, not unverified customer claims."""
        return self.domain.execute("get_payment_history", {"invoice_id":invoice_id}, call_id=context.function_call.call_id).model_dump(mode="json")

    @function_tool
    async def log_dispute(self, context: RunContext[SessionState], reason: Reason):
        """Record the current customer concern; permanently pause collection and simulate human review."""
        return self.domain.execute("log_dispute", {"reason":reason}, call_id=context.function_call.call_id).model_dump(mode="json")

    @function_tool
    async def escalate_to_human(self, context: RunContext[SessionState]):
        """Mark one simulated human-review case and pause automated collection; no real contact."""
        return self.domain.execute("escalate_to_human", {}, call_id=context.function_call.call_id).model_dump(mode="json")

    @function_tool
    async def send_followup_email(self, context: RunContext[SessionState]):
        """Create an inspectable simulated email only with customer consent; suppression always wins."""
        return self.domain.execute("send_followup_email", {}, call_id=context.function_call.call_id).model_dump(mode="json")

    async def llm_node(self, chat_ctx, tools, model_settings):
        async with self._generation_lock:
            try:
                message = next((m for m in reversed(chat_ctx.items) if isinstance(m, llm.ChatMessage) and m.role == "user"), None)
                if message is None:
                    raise LimitError("Please enter an invoice question.")
                if message.id != self.state.last_message_id:
                    text = message.text_content or ""
                    scope = "public-voice" if self.state.voice_lease else self.provider.scope
                    await self.provider.guards.turn(self.state, text, scope)
                    self.provider.scope = scope
                    self.state.last_message_id = message.id
                    self.state.last_customer_turn = text
                    self.state.turn_id = new_id()
                    self.state.customer_turns.append({"turn_id":self.state.turn_id,"text":text})
                    self.state.requests = self.state.reserved_tokens = 0
                schema = ReplyPlan.model_json_schema()
                ctx = chat_ctx.copy()
                ctx.add_message(role="system", content="Session-local available fact catalog: " + str([f.model_dump() for f in self.state.facts.values()]) +
                    f" Collection hold={self.state.collection_hold}; contact suppressed={self.state.contact_suppressed}.")
                content, has_tools = [], False
                async with self.provider.llm.chat(chat_ctx=ctx, tools=tools,
                    tool_choice=model_settings.tool_choice,
                    conn_options=self.session.conn_options.llm_conn_options,
                    extra_kwargs={"text":{"format":{"type":"json_schema","name":"ReplyPlan","strict":True,"schema":schema}}}) as stream:
                    async for chunk in stream:
                        if chunk.usage:
                            self.state.usage.append(chunk.usage.model_dump())
                        if chunk.delta and chunk.delta.content:
                            content.append(chunk.delta.content)
                        if chunk.delta and chunk.delta.tool_calls:
                            has_tools = True
                        # Forward tool calls/usage, never raw structured output or preambles.
                        forwarded = chunk.model_copy(deep=True)
                        if forwarded.delta:
                            forwarded.delta.content = None
                        yield forwarded
                if not has_tools:
                    plan = ReplyPlan.model_validate_json("".join(content))
                    text, sources = render(plan, self.state)
                    self._pending_sources = {"text":text,"facts":sources,"non_factual":{"acknowledgement":plan.acknowledgement,"question":plan.question}}
                    yield text
            except LimitError as exc:
                self.state.event("limit", {"message":str(exc)})
                yield str(exc)
            except Exception:
                self.state.event("error", {"code":"SAFE_REPLY_ERROR", "message":SAFE_ERROR})
                yield SAFE_ERROR

    async def stt_node(self, audio, model_settings):
        try:
            async for event in Agent.default.stt_node(self, audio, model_settings):
                yield event
        except Exception:
            if self.voice:
                self.voice.schedule_off("Speech recognition failed; text remains available.")

    async def tts_node(self, text, model_settings):
        try:
            async for frame in Agent.default.tts_node(self, text, model_settings):
                yield frame
        except Exception:
            if self.voice:
                self.voice.schedule_off("Speech playback failed; the full text remains visible.")
