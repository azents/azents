"""Pure deterministic Historical Memory model fixture contract tests."""

import json

import pytest

from support.image_generation_openai_proxy import (
    historical_memory_inspection,
    historical_memory_summary_response,
)


def _request(source: str) -> dict[str, object]:
    return {
        "input": [{"role": "user", "content": source}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "historical_memory",
                "strict": True,
                "schema": {
                    "additionalProperties": False,
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                },
            },
        },
    }


def test_summary_fixture_requires_schema_and_qualifies_evidence() -> None:
    """Fixture generation preserves corrections and uncertainty, not fake success."""
    response = historical_memory_summary_response(
        _request("Historical Memory E2E source: use blue, red was only a proposal."),
    )
    assert response is not None
    summary = json.loads(response)["summary"]
    assert "User correction" in summary
    assert "not a production deployment" in summary
    assert "Unfinished work" in summary
    assert "Delivery uncertainty" in summary
    request = _request("Historical Memory E2E source")
    request["text"] = {"format": {"name": "historical_memory", "strict": False}}
    with pytest.raises(ValueError, match="strict"):
        historical_memory_summary_response(request)


def test_summary_fixture_isolated_and_supports_validation_cases() -> None:
    """Other tests cannot acquire Historical fixture behavior accidentally."""
    assert historical_memory_summary_response(_request("Other feature source")) is None
    assert (
        historical_memory_summary_response(_request("Historical Memory E2E empty"))
        == '{"summary":""}'
    )
    malformed = historical_memory_summary_response(
        _request("Historical Memory E2E malformed")
    )
    assert malformed is not None
    assert json.loads(malformed)["summary"] == 42
    oversized = historical_memory_summary_response(
        _request("Historical Memory E2E oversized")
    )
    assert oversized is not None
    assert len(json.loads(oversized)["summary"].encode()) > 9_000


def test_inspection_uses_current_user_and_unique_call_identity() -> None:
    """One latest-user fixture cannot repeat a preceding Session operation."""
    prefix = "Historical Memory E2E inspect "
    request: dict[str, object] = {
        "input": [
            {
                "role": "user",
                "content": prefix + '{"operation":"read","path":"/tmp/old"}',
            },
            {
                "role": "user",
                "content": prefix
                + '{"operation":"glob","path":"azents://memory/saved/agent/*.md"}',
            },
        ]
    }
    result = historical_memory_inspection(request)
    assert result is not None
    assert result.call_id.startswith("call_historical_memory_")
    assert result.name == "glob"
    assert result.arguments == {"pattern": "azents://memory/saved/agent/*.md"}
