"""Docker-free coverage for decoding folder setup in the shared idle helper."""

import json
from unittest.mock import patch

import pytest
import requests

from tests.required.public.test_run_tool_to_file import _live_idle


@pytest.mark.parametrize("run_state", ["idle", "running"])
def test_live_idle_decodes_generated_nested_folder_result(run_state: str) -> None:
    """Decode scalar/null setup results while keeping the idle assertion."""
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(
        {
            "partial_history": {"items": []},
            "mailbox_items": [],
            "session_run_state": run_state,
            "action_executions": [
                {
                    "execution": {
                        "id": "execution-1",
                        "source_mailbox_item_id": "mailbox-1",
                        "sender_user_id": None,
                        "action_type": "create_session_working_folder",
                        "action": {"type": "create_session_working_folder"},
                        "result": {
                            "phase": "completed",
                            "outcome": "ready",
                            "reason_code": None,
                        },
                        "status": "completed",
                        "owner_generation": 1,
                        "updated_at": "2026-10-26T00:00:00Z",
                    },
                    "events": [],
                }
            ],
        }
    ).encode()
    with patch(
        "tests.required.public.test_run_tool_to_file.requests.get",
        return_value=response,
    ) as get:
        assert _live_idle(
            server_url="https://azents.test",
            token="test-token",
            session_id="session-1",
        ) is (run_state == "idle")
    get.assert_called_once_with(
        "https://azents.test/chat/v1/sessions/session-1/live",
        headers={"Authorization": "Bearer test-token"},
        timeout=10,
    )
