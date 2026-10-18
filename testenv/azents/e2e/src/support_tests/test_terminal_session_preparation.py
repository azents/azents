"""Session preparation follows open authority rather than ended-metadata expiry."""

from unittest.mock import Mock, patch

import azentspublicclient
from azentspublicclient.models.runtime_terminal_projection_response import (
    RuntimeTerminalProjectionResponse,
)

from tests.required.public import test_runtime_terminal as terminal


def test_preparation_waits_for_open_authority_including_ended_terminal() -> None:
    workspace = terminal._TerminalWorkspace(
        token="synthetic-token",
        handle="synthetic",
        agent_id="agent",
        session_id="session",
    )
    folder = Mock()
    folder_ready = Mock()
    projection = Mock()
    with (
        azentspublicclient.ApiClient() as client,
        patch.object(terminal, "_prepare_session_folder", folder),
        patch.object(terminal, "_wait_session_folder_ready", folder_ready),
        patch.object(terminal, "_wait_terminal_projection", projection),
    ):
        terminal._prepare_terminal_session(
            public_api_client=client,
            workspace=workspace,
            server_url="http://unused.test",
        )
    folder.assert_called_once()
    folder_ready.assert_called_once()
    projection.assert_called_once()
    predicate = projection.call_args.kwargs["predicate"]
    for state in ("ready", "active", "ended"):
        for authorized in (False, True):
            observed = RuntimeTerminalProjectionResponse(
                state=state,
                reason_code=None,
                denied_scope=None,
                can_start_runtime=False,
                can_open_or_attach=authorized,
                terminal=None,
            )
            assert predicate(observed) is authorized
    assert folder_ready.call_args.kwargs["deadline"] > 0
    assert 0 < projection.call_args.kwargs["timeout"] <= 120
