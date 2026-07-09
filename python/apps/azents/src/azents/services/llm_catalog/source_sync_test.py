"""LiteLLM source sync tests."""

from azents.services.llm_catalog import current_litellm_model_cost_payload


def test_current_litellm_model_cost_payload_is_available() -> None:
    """LiteLLM runtime exposes a non-empty model cost map."""
    payload = current_litellm_model_cost_payload()

    assert payload
    assert all(isinstance(key, str) for key in payload)
