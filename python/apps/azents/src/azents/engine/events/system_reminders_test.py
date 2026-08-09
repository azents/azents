"""System reminder rendering tests."""

from azents.engine.events.system_reminders import (
    format_external_channel_continuation_reminder,
)


def test_external_channel_continuation_instructs_silent_completion() -> None:
    """A stale binding must be explicitly completed instead of left cycling."""
    reminder = format_external_channel_continuation_reminder(
        {"active_bindings": "binding-1"}
    )

    assert '`mode="ignore"`' in reminder
    assert "binding-1" in reminder
    assert "Do not include a message, title, task update, or files." in reminder
    assert "does not schedule another continuation" in reminder
