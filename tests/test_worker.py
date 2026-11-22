import json
import time
import jwt
import pytest
from collections_agent.worker import verify_binding
from collections_agent.settings import Settings


def token(**changes):
    now=int(time.time())
    data={"iss":"dispute-safe-collections","aud":"worker","iat":now,"exp":now+600,
          "session_id":"s","visitor_id":"v","ip_hash":"h","participant_identity":"p","room":"r",
          "customer_id":"CUST-1001","invoice_id":"INV-2026-1042","prompt_version":"v2","deadline":now+600}
    data.update(changes)
    return json.dumps({"bindingJwt":jwt.encode(data,"x"*32,algorithm="HS256")})


def test_signed_dispatch_is_account_and_room_bound():
    settings=Settings(_env_file=None,livekit_api_secret="x"*32)
    assert verify_binding(token(),settings,"r")["invoice_id"] == "INV-2026-1042"
    for changes in [{"invoice_id":"INV-2026-1043"},{"customer_id":"CUST-1002"},{"deadline":int(time.time())+6010},{"prompt_version":"injected"}]:
        with pytest.raises(ValueError):
            verify_binding(token(**changes),settings,"r")
    with pytest.raises(ValueError):
        verify_binding(token(),settings,"other-room")
    with pytest.raises(jwt.InvalidSignatureError):
        verify_binding(token(),Settings(_env_file=None,livekit_api_secret="y"*32),"r")
