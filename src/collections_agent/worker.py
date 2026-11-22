"""LiveKit owns transport, turn handling, text streams and speech pipelines."""
import asyncio
import json
import time
import jwt
from livekit import api, rtc
from livekit.agents import AgentServer, JobContext, cli, room_io
from .limits import redis_client, require_budget
from .models import SessionState
from .session import create_session
from .settings import Settings
from .telemetry import Publisher

NAME = "dispute-safe-collections"
server = AgentServer()


def verify_binding(metadata: str, settings: Settings, room_name: str) -> dict:
    token = json.loads(metadata)["bindingJwt"]
    binding = jwt.decode(token, settings.livekit_api_secret, algorithms=["HS256"],
        audience="worker", issuer=NAME, options={"require":["exp","iat","session_id","visitor_id","ip_hash","participant_identity","room","deadline","customer_id","invoice_id","prompt_version"]})
    if binding["room"] != room_name or binding["deadline"] <= time.time():
        raise ValueError("Invalid room/deadline")
    if binding["customer_id"] != "CUST-1001" or binding["invoice_id"] != "INV-2026-1042" or binding["prompt_version"] not in {"v1","v2"}:
        raise ValueError("Invalid account/prompt binding")
    if binding["deadline"] > binding["iat"] + 600:
        raise ValueError("Session deadline exceeds maximum")
    return binding


@server.rtc_session(agent_name=NAME)
async def entrypoint(ctx: JobContext):
    settings = Settings()
    require_budget(settings, "public-text")
    binding = verify_binding(ctx.job.metadata, settings, ctx.job.room.name)
    redis = redis_client(settings)
    sid, visitor = binding["session_id"], binding["visitor_id"]
    ttl = max(1, int(binding["deadline"] - time.time()))
    if await redis.get(f"collections:occupancy:{visitor}") != sid:
        raise ValueError("Session lease missing")
    # A worker restart cannot pretend an in-memory conversation survived.
    fresh = await redis.set(f"collections:worker-started:{sid}", "1", nx=True, ex=ttl)
    if not fresh:
        await ctx.api.room.delete_room(api.DeleteRoomRequest(room=binding["room"]))
        raise ValueError("Worker restart ended this demo; start a new session")
    state = SessionState(session_id=sid,visitor_id=visitor,ip_hash=binding["ip_hash"],
        participant_identity=binding["participant_identity"],prompt_version=binding["prompt_version"])
    session, agent, provider = create_session(settings, state)
    publisher = None
    voice = None
    finished = asyncio.Event()
    activity = time.monotonic()

    def touch(*args):
        nonlocal activity
        activity = time.monotonic()

    async def release():
        await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
            keys=[f"collections:occupancy:{visitor}"], args=[sid])
        await redis.delete(f"collections:session:{sid}")

    try:
        await ctx.connect()
        participant = await asyncio.wait_for(ctx.wait_for_participant(identity=state.participant_identity),30)
        publisher = Publisher(ctx.room, state)

        @ctx.room.local_participant.register_rpc_method("collections.sync")
        async def sync(data: rtc.RpcInvocationData):
            body = json.loads(data.payload)
            after = body.get("after",0)
            if type(after) is not int:
                raise ValueError("Invalid sequence")
            return json.dumps(await publisher.sync(data.caller_identity, after))

        @ctx.room.on("participant_connected")
        def joined(remote):
            if remote.identity != state.participant_identity:
                # No unbound participant may share this single-visitor room.
                finished.set()

        @ctx.room.on("participant_disconnected")
        def left(remote):
            if remote.identity == state.participant_identity:
                finished.set()

        @session.on("conversation_item_added")
        def message(event):
            touch()

        @session.on("agent_state_changed")
        def agent_activity(event):
            touch()

        @session.on("user_input_transcribed")
        def user_activity(event):
            touch()

        @session.on("close")
        def closed(event):
            finished.set()

        await session.start(agent=agent,room=ctx.room,room_options=room_io.RoomOptions(
            participant_identity=participant.identity,video_input=False,
            audio_input=room_io.AudioInputOptions(pre_connect_audio=False),
            text_output=room_io.TextOutputOptions(sync_transcription=False),
            close_on_disconnect=True))
        # Audio-capable RoomIO remains attached for an opt-in same-agent switch.
        from .voice import VoiceController
        voice = VoiceController(agent,session,ctx.room,redis)
        voice.register()
        state.event("voice_state", {"enabled":False,"available":False,"message":"Voice is opt-in and requires verified no-charge access."})
        while not finished.is_set():
            remaining = min(binding["deadline"]-time.time(), 60-(time.monotonic()-activity))
            if remaining <= 0:
                state.event("limit", {"message":"Demo closed: session deadline or inactivity limit reached. Start a new demo."})
                break
            try:
                await asyncio.wait_for(finished.wait(),timeout=min(remaining,1))
            except TimeoutError:
                pass
    finally:
        if voice:
            await voice.off("Session ended.")
        await session.aclose()
        await provider.close()
        if publisher:
            await publisher.close()
        await release()
        if ctx.room.isconnected():
            await ctx.api.room.delete_room(api.DeleteRoomRequest(room=binding["room"]))
        ctx.shutdown(reason="Demo session ended")


if __name__ == "__main__":
    cli.run_app(server)
