"""Metadata-derived control selection and unrelated-option preservation."""

import pytest

from azents.core.model_execution_options import (
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
)
from azents.services.external_channel.model_execution_controls import (
    decode_execution_control,
    update_execution_control,
)


@pytest.mark.parametrize("selected", ["__normal__:custom_speed", "ultrafast"])
def test_speed_control_preserves_unrelated_execution_options(selected: str) -> None:
    """Use metadata even when group membership differs from production IDs."""
    definitions = [
        definition.model_copy(
            update={
                "exclusive_group": "custom_speed"
                if definition.id is ModelExecutionOptionId.ULTRAFAST
                else None
            }
        )
        for definition in list_model_execution_option_definitions()
    ]
    decoded = decode_execution_control([selected])
    updated = update_execution_control(
        definitions=definitions,
        current=[ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        selected=decoded.enabled,
        cleared_group=decoded.cleared_group,
    )
    assert ModelExecutionOptionId.FAST in updated
    assert (ModelExecutionOptionId.ULTRAFAST in updated) == (selected == "ultrafast")


def test_independent_control_clear_preserves_group_selection() -> None:
    definitions = [
        definition.model_copy(
            update={
                "exclusive_group": None
                if definition.id is ModelExecutionOptionId.FAST
                else "custom_speed"
            }
        )
        for definition in list_model_execution_option_definitions()
    ]
    assert update_execution_control(
        definitions=definitions,
        current=[ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST],
        selected=[],
        cleared_group=None,
    ) == [ModelExecutionOptionId.ULTRAFAST]


@pytest.mark.parametrize(
    "selected,cleared_group",
    [
        ([ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST], None),
        ([ModelExecutionOptionId.FAST, ModelExecutionOptionId.FAST], None),
        ([ModelExecutionOptionId.FAST], "processing_speed"),
        ([], "unknown"),
    ],
)
def test_control_merge_rejects_forged_conflicting_or_unknown_group(
    selected: list[ModelExecutionOptionId], cleared_group: str | None
) -> None:
    with pytest.raises(ValueError):
        update_execution_control(
            definitions=list_model_execution_option_definitions(),
            current=[],
            selected=selected,
            cleared_group=cleared_group,
        )
