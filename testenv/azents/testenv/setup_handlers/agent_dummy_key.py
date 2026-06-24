"""Setup handler: ``agent-dummy-key``.

Creates an agent from the dummy-key OpenAI integration and default runtime
settings, then stores ``agent.*`` in run-scope state.

Environment:
    STATE_FILE — state.json path.
"""

import sys
from pathlib import Path

_TESTENV_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_TESTENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTENV_ROOT))

from testenv.client import build_client_from_env  # noqa: E402
from testenv.seed.types import Integration, User, Workspace  # noqa: E402
from testenv.state import state_from_env  # noqa: E402

DUMMY_SLUG = "gpt-4o-mini"
"""Dummy agent model slug used by tests."""


def main() -> int:
    """Create a dummy-key agent."""
    client = build_client_from_env()
    state = state_from_env()
    bucket = state.run

    u = bucket.get("user") or {}
    w = bucket.get("ws") or {}
    i = bucket.get("integration") or {}
    if (
        not u.get("access_token")
        or not w.get("handle")
        or not i.get("id")
        or not i.get("model_config_id")
    ):
        print(
            "ERROR: run test-user-workspace + llm-provider-dummy setups first",
            file=sys.stderr,
        )
        return 2

    user = User(
        email=u["email"],
        access_token=u["access_token"],
        refresh_token=u.get("refresh_token") or "",
    )
    ws = Workspace(handle=w["handle"], name=w.get("name") or "", owner=user)
    integration = Integration(
        id=i["id"],
        workspace=ws,
        provider=i.get("provider") or "",
        name=i.get("name") or "",
    )

    agent = client.agent.create(
        user,
        ws,
        integration,
        DUMMY_SLUG,
        model_config_id=i["model_config_id"],
    )

    bucket.setdefault("agent", {}).update(
        {
            "id": agent.id,
            "model_slug": DUMMY_SLUG,
        }
    )
    state.save()
    print(f"SEEDED agent.id={agent.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
