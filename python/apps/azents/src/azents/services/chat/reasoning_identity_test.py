"""Native reasoning identity boundary tests."""

import dataclasses
from collections.abc import Mapping

import pytest

from .live_events import _decode_reasoning_identity


@pytest.mark.parametrize(
    ("item", "item_id", "output_index", "summary_index"),
    [
        ({}, None, None, None),
        ({"id": "", "output_index": -1, "summary_index": 0}, "", -1, 0),
        ({"id": "item", "output_index": 3, "summary_index": -2}, "item", 3, -2),
        ({"id": 3, "output_index": True, "summary_index": False}, None, None, None),
        ({"id": None, "output_index": "3", "summary_index": 1.5}, None, None, None),
        ({"id": [], "output_index": None, "summary_index": {}}, None, None, None),
    ],
)
def test_reasoning_identity_preserves_existing_fallbacks(
    item: Mapping[str, object],
    item_id: str | None,
    output_index: int | None,
    summary_index: int | None,
) -> None:
    identity = _decode_reasoning_identity(item)
    assert identity.item_id == item_id
    assert identity.output_index == output_index
    assert identity.summary_index == summary_index


def test_reasoning_identity_keeps_native_extensions_opaque() -> None:
    extension = {"provider": ["opaque", 1]}
    item: dict[str, object] = {
        "id": "native-item",
        "output_index": 1,
        "extension": extension,
    }
    before = dict(item)
    identity = _decode_reasoning_identity(item)
    assert item == before
    assert item["extension"] is extension
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.item_id = "changed"  # ty: ignore[invalid-assignment] -- verify frozen projection
