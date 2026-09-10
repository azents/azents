"""Deterministic image-generation catalog proxy tests."""

from support.image_generation_openai_proxy import (
    image_generation_model_list_payload,
)


def test_image_model_listing_contains_registry_and_unregistered_ids() -> None:
    """Provider listing exercises exact registry intersection."""
    payload = image_generation_model_list_payload()
    data = payload["data"]

    assert isinstance(data, list)
    identifiers = {
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    assert identifiers == {
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
        "provider-visible-unregistered-image-model",
    }
    assert payload["has_more"] is False
