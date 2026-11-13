"""Synthetic models select logical work from their actual model-visible input."""

import pytest

from support.image_generation_openai_proxy import selected_work_arguments


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        (
            "channel_action",
            "Work cycle IDs: " + "a" * 32,
            {"work_cycle_id": "a" * 32, "scheduled_cycle_id": None},
        ),
        (
            "channel_action",
            "Work cycle ID: " + "a" * 32 + "\nWork cycle IDs: " + "b" * 32,
            {"work_cycle_id": "b" * 32, "scheduled_cycle_id": None},
        ),
        (
            "channel_action",
            "Explicit ordinary new publication",
            {"work_cycle_id": None, "scheduled_cycle_id": None},
        ),
        (
            "submit_scheduled_task_result",
            "Cycle ID: " + "c" * 32,
            {"cycle_id": "c" * 32},
        ),
    ],
)
def test_model_fixture_selects_visible_work(
    name: str,
    text: str,
    expected: dict[str, object],
) -> None:
    request: dict[str, object] = {"input": [{"role": "user", "content": text}]}
    assert selected_work_arguments(request, name=name, arguments={}) == expected


def test_model_fixture_cannot_invent_scheduled_cycle() -> None:
    with pytest.raises(ValueError, match="no exact cycle selector"):
        selected_work_arguments(
            {"input": [{"role": "user", "content": "Title alone is not identity"}]},
            name="submit_scheduled_task_result",
            arguments={},
        )
