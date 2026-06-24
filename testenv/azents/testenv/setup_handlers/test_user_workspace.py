"""Setup handler: ``test-user-workspace``.

Creates an azents user and workspace, then stores ``user.*`` and ``ws.*`` in
run-scope ``state.json``. This is the base prerequisite for the agent-basic
fixture.

Environment:
    STATE_FILE — state.json path.
"""

import sys
from pathlib import Path

_TESTENV_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_TESTENV_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTENV_ROOT))

from testenv.client import build_client_from_env  # noqa: E402
from testenv.state import state_from_env  # noqa: E402


def main() -> int:
    """Create a user and workspace, then store them in run scope."""
    client = build_client_from_env()
    user = client.auth.create_user()
    ws = client.workspace.create(user)

    state = state_from_env()
    bucket = state.run
    bucket.setdefault("user", {}).update(
        {
            "email": user.email,
            "access_token": user.access_token,
            "refresh_token": user.refresh_token,
        }
    )
    bucket.setdefault("ws", {}).update(
        {
            "handle": ws.handle,
            "name": ws.name,
        }
    )
    state.save()
    print(f"SEEDED user={user.email} ws={ws.handle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
