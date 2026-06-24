"""Expect DSL run unit tests."""

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from testenv.assertions import all_passed, parse_expect_block, run_expect_block
from testenv.types import AssertionResult


def _run(
    expect_raw: Mapping[str, object],
    actual: Mapping[str, object],
) -> list[AssertionResult]:
    """Smoke test: parse raw dict and call run_expect_block."""
    return list(run_expect_block(parse_expect_block(expect_raw), actual))


def test_http_status_pass() -> None:
    """http_status match passes."""
    results = _run({"http_status": 200}, {"http_status": 200})
    assert len(results) == 1
    assert results[0].passed is True


def test_http_status_fail() -> None:
    """http_status mismatch fails."""
    results = _run({"http_status": 200}, {"http_status": 500})
    assert results[0].passed is False


def test_response_body_contains_and_not_contains() -> None:
    """contains and not_contains assertions both run."""
    expect = {
        "response_body": {
            "contains": ["Connected to"],
            "not_contains": ["AuthenticationError", "Traceback"],
        }
    }
    actual = {"response_body": "Connected to webhook"}
    results = _run(expect, actual)
    assert all_passed(results)
    # 3 assertions
    assert len(results) == 3


def test_not_contains_catches_llm_error() -> None:
    """not_contains absence is a passing guard against LLM error text."""
    expect = {"response_body": {"not_contains": ["AuthenticationError"]}}
    actual = {"response_body": "AuthenticationError: invalid api key"}
    results = _run(expect, actual)
    assert results[0].passed is False


def test_json_path_equals() -> None:
    """Resolve dotted jsonpath."""
    expect = {
        "response_body": {
            "json_path": [
                {"path": "$.mode", "equals": "byoa"},
                {"path": "$.app_id", "matches": "^A[0-9A-Z]+$"},
            ],
        }
    }
    actual = {"response_body": {"mode": "byoa", "app_id": "A12345678"}}
    results = _run(expect, actual)
    assert all_passed(results)


def test_json_path_miss() -> None:
    """Missing path returns actual=None and equals fails."""
    expect = {"response_body": {"json_path": [{"path": "$.missing", "equals": "x"}]}}
    actual = {"response_body": {"mode": "byoa"}}
    results = _run(expect, actual)
    assert results[0].passed is False


def test_bot_reply_status_and_latency() -> None:
    """bot_reply assertions run."""
    expect = {
        "bot_reply": {
            "status": "posted",
            "latency_s": {"max": 30},
            "text": {"not_contains": ["AuthenticationError"]},
        }
    }
    actual = {
        "bot_reply": {
            "status": "posted",
            "latency_s": 2.5,
            "text": "Hello world",
        }
    }
    results = _run(expect, actual)
    assert all_passed(results)


def test_bot_reply_latency_exceeds() -> None:
    """Latency range assertions run."""
    expect = {"bot_reply": {"latency_s": {"max": 10}}}
    actual = {"bot_reply": {"latency_s": 45}}
    results = _run(expect, actual)
    assert results[0].passed is False


# ----- pydantic strict validation ------------------------------------------


def test_unknown_top_level_field_rejected() -> None:
    """Top-level unknown fields raise ValidationError and block the TC."""
    with pytest.raises(ValidationError) as exc:
        parse_expect_block({"http_statuss": 200})  # typo
    assert "http_statuss" in str(exc.value)


def test_unknown_nested_field_rejected() -> None:
    """Nested unknown fields are blocked."""
    with pytest.raises(ValidationError):
        parse_expect_block({"response_body": {"contain": ["x"]}})  # contains typo


def test_http_status_out_of_range_rejected() -> None:
    """HTTP status codes outside 100-599 raise ValidationError."""
    with pytest.raises(ValidationError):
        parse_expect_block({"http_status": 99})
    with pytest.raises(ValidationError):
        parse_expect_block({"http_status": 600})


def test_min_length_negative_rejected() -> None:
    """min_length is validated."""
    with pytest.raises(ValidationError):
        parse_expect_block({"response_body": {"min_length": -1}})


def test_latency_max_non_positive_rejected() -> None:
    """latency_s.max must be greater than zero."""
    with pytest.raises(ValidationError):
        parse_expect_block({"bot_reply": {"latency_s": {"max": 0}}})


def test_bot_reply_status_literal_only() -> None:
    """bot_reply.status only allows posted or not_posted."""
    with pytest.raises(ValidationError):
        parse_expect_block({"bot_reply": {"status": "pending"}})  # invalid enum value


def test_json_path_unknown_field_rejected() -> None:
    """json_path unknown fields are blocked."""
    with pytest.raises(ValidationError):
        parse_expect_block({"response_body": {"json_path": [{"path": "$.x", "eq": "y"}]}})
