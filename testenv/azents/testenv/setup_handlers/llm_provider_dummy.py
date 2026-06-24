"""Setup handler: ``llm-provider-dummy``.

Creates a dummy OpenAI integration for verifying the LLM path and stores
``integration.*`` in run-scope state. This is used for event checks that do not
require an actual LLM call.

Environment:
    STATE_FILE — state.json path.
"""

import sys
from pathlib import Path

_TESTENV_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_TESTENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTENV_ROOT))

from testenv.client import build_client_from_env  # noqa: E402
from testenv.seed.types import User, Workspace  # noqa: E402
from testenv.state import state_from_env  # noqa: E402


def main() -> int:
    """Create an OpenAI integration with a dummy API key."""
    client = build_client_from_env()
    state = state_from_env()
    bucket = state.run

    u = bucket.get("user") or {}
    w = bucket.get("ws") or {}
    if not u.get("access_token") or not w.get("handle"):
        print("ERROR: run test-user-workspace setup first", file=sys.stderr)
        return 2

    user = User(
        email=u["email"],
        access_token=u["access_token"],
        refresh_token=u.get("refresh_token") or "",
    )
    ws = Workspace(handle=w["handle"], name=w.get("name") or "", owner=user)

    integration = client.llm.create_integration(
        user,
        ws,
        name="__testenv_model_listing:deterministic-success",
    )
    model_config_id = client.llm.create_model_config_from_first_candidate(
        user,
        ws,
        integration,
        label="Testenv default model",
    )

    bucket.setdefault("integration", {}).update(
        {
            "id": integration.id,
            "provider": integration.provider,
            "name": integration.name,
            "model_config_id": model_config_id,
        }
    )
    state.save()
    print(f"SEEDED integration.id={integration.id} model_config.id={model_config_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
