"""Action message contract tests."""

import pytest
from pydantic import TypeAdapter, ValidationError

from .action_messages import (
    ActionMessagePayload,
    ChatAction,
    CreateSessionWorkingFolderAction,
    PersistedChatAction,
)


def test_public_chat_action_rejects_session_working_folder_setup() -> None:
    """Users cannot author the pathless Session-folder setup action."""
    with pytest.raises(ValidationError):
        TypeAdapter(ChatAction).validate_python(
            {"type": "create_session_working_folder"}
        )


@pytest.mark.parametrize(
    "action",
    [
        {
            "type": "agent_create_git_worktree",
            "bridge_identity": "bridge-001",
            "originating_run_id": "run-001",
            "client_tool_call_id": "call-001",
            "session_agent_context_id": "context-001",
            "originating_agent_session_id": "session-001",
            "source_project_id": "project-001",
            "source_project_path": "/workspace/agent/repo",
            "starting_ref": None,
            "branch_name": None,
        },
        {
            "type": "agent_remove_git_worktree",
            "bridge_identity": "bridge-002",
            "originating_run_id": "run-002",
            "client_tool_call_id": "call-002",
            "session_agent_context_id": "context-002",
            "originating_agent_session_id": "session-002",
            "worktree_project_id": "project-002",
            "worktree_allocation_id": "allocation-002",
            "worktree_path": "/workspace/agent/worktree",
            "force": False,
        },
    ],
)
def test_public_chat_action_rejects_internal_agent_worktree_bridge(
    action: dict[str, object],
) -> None:
    """Users cannot author the internal Agent worktree bridge actions."""
    with pytest.raises(ValidationError):
        TypeAdapter(ChatAction).validate_python(action)


def test_persisted_action_and_history_accept_session_working_folder_setup() -> None:
    """Durable execution and history can decode the system-only action."""
    action = TypeAdapter(PersistedChatAction).validate_python(
        {"type": "create_session_working_folder"}
    )
    assert isinstance(action, CreateSessionWorkingFolderAction)

    payload = ActionMessagePayload(
        sender_user_id=None,
        action=action,
        message="",
    )
    assert payload.action.type == "create_session_working_folder"
