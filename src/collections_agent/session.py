from livekit.agents import AgentSession, APIConnectOptions, llm
from livekit.agents.voice import SessionConnectOptions
from .agent import CollectionsAgent
from .fixtures import load_fixture
from .limits import Guards
from .models import SessionState
from .provider import Provider
from .settings import Settings
from .telemetry import attach_tool_events


def create_session(settings: Settings | None = None, state: SessionState | None = None, *, scope="public-text", transport=None, guards=None):
    settings = settings or Settings()
    load_fixture()  # invalid fixture is a startup error, never replaced with invented facts
    state = state or SessionState(prompt_version=settings.prompt_version)
    provider = Provider(settings, state, guards or Guards(settings), scope, transport)
    agent = CollectionsAgent(state, provider)
    session = AgentSession[SessionState](userdata=state, llm=provider.llm, max_tool_steps=5,
        turn_handling={"turn_detection":"manual", "preemptive_generation":{"enabled":False}},
        user_away_timeout=None, conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(max_retry=0), stt_conn_options=APIConnectOptions(max_retry=0),
            tts_conn_options=APIConnectOptions(max_retry=0)))
    session.input.set_audio_enabled(False)
    session.output.set_audio_enabled(False)

    @session.on("conversation_item_added")
    def reply_sources(event):
        if not isinstance(event.item, llm.ChatMessage):
            return
        pending = getattr(agent, "_pending_sources", None)
        if event.item.role == "assistant" and pending and event.item.text_content == pending["text"]:
            state.event("reply_sources", {"message_id":event.item.id, **pending})
            agent._pending_sources = None
        if event.item.role == "assistant" and event.item.metrics:
            state.event("latency", {"message_id":event.item.id,"unit":"seconds", "metrics":event.item.metrics})
    attach_tool_events(session, agent)
    return session, agent, provider
