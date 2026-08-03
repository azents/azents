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
