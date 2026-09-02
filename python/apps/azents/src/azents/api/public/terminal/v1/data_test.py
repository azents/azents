"""Public Runtime Terminal schema tests."""

import pytest
from pydantic import ValidationError

from azents.api.public.terminal.v1.data import (
    TERMINAL_CLIENT_CONTROL_ADAPTER,
    TerminalAttachControl,
    TerminalResizeControl,
)


def test_terminal_controls_are_closed_and_discriminated() -> None:
    control = TERMINAL_CLIENT_CONTROL_ADAPTER.validate_python(
        {"type": "resize", "sequence": 2, "columns": 120, "rows": 40}
    )

    assert control == TerminalResizeControl(
        type="resize",
        sequence=2,
        columns=120,
        rows=40,
    )
    with pytest.raises(ValidationError):
        TERMINAL_CLIENT_CONTROL_ADAPTER.validate_python(
            {
                "type": "resize",
                "sequence": 2,
                "columns": 120,
                "rows": 40,
                "unknown": True,
            }
        )


def test_attach_control_rejects_unknown_fields_and_invalid_dimensions() -> None:
    with pytest.raises(ValidationError):
        TerminalAttachControl.model_validate(
            {"type": "attach", "columns": 0, "rows": 40}
        )
    with pytest.raises(ValidationError):
        TerminalAttachControl.model_validate(
            {
                "type": "attach",
                "columns": 80,
                "rows": 24,
                "unexpected": "value",
            }
        )
