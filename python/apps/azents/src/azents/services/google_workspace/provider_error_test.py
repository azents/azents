"""Provider diagnostics preserve bounded original response-owned fields."""

import json

import pytest

from azents.services.google_workspace.provider_error import decode_provider_error


@pytest.mark.parametrize(
    "payload",
    [b"bad json", b"[]", b"{}", b'{"error":"private"}', b'{"error":{"message":42}}'],
)
def test_malformed_provider_errors_do_not_echo_untyped_body(payload: bytes) -> None:
    assert decode_provider_error(payload) is None


def test_messages_and_unknown_reasons_are_preserved_without_an_allowlist() -> None:
    message = (
        "Unknown Google failure for user@example.com, project 123, file resource-42."
    )
    error = decode_provider_error(
        json.dumps(
            {
                "error": {
                    "status": "FUTURE_STATUS",
                    "message": message,
                    "errors": [{"reason": "newReason"}],
                    "details": [{"reason": "NEW_REASON"}],
                }
            }
        ).encode()
    )
    assert error is not None
    assert error.message == message
    assert error.reasons == ("newReason", "NEW_REASON")
    assert error.status == "FUTURE_STATUS"


def test_original_fields_are_bounded() -> None:
    message = "token/a+b token%2Fa%2Bb " + "x" * 4000
    reasons = [f"reason-{index}-" + "r" * 256 for index in range(15)]
    error = decode_provider_error(
        json.dumps(
            {
                "error": {
                    "message": message,
                    "status": "s" * 300,
                    "errors": [{"reason": reason} for reason in reasons],
                }
            }
        ).encode()
    )
    assert error is not None
    assert error.message == message[:4000]
    assert error.status == "s" * 256
    assert error.reasons == tuple(reason[:256] for reason in reasons[:10])


def test_only_diagnostic_fields_cross_boundary() -> None:
    error = decode_provider_error(
        b'{"error":{"message":"Useful message","debug":{"request":"private"},'
        b'"errors":[{"reason":"denied","request":"private"}]}}'
    )
    assert error is not None
    assert error.model_dump() == {
        "status": None,
        "reasons": ("denied",),
        "message": "Useful message",
    }


@pytest.mark.parametrize(
    "text",
    [
        'client_secret="credential,tail"',
        'password="two words"',
        'refresh_token="fixture&tail"',
        r'client_secret="escaped\"quote,tail"',
        r"password='escaped\'quote & tail'",
        r'api_key="escaped\\slash,tail"',
        '"refresh_token": "fixture & tail"',
        "Authorization: Bearer original-provider-text",
    ],
)
def test_provider_text_is_preserved_in_all_diagnostic_fields(text: str) -> None:
    message = f"Project 123 user@example.com {text}; https://example.com"
    error = decode_provider_error(
        json.dumps(
            {
                "error": {
                    "message": message,
                    "status": message,
                    "errors": [{"reason": message}],
                }
            }
        ).encode()
    )
    assert error is not None
    assert error.message == message
    assert error.status == message
    assert error.reasons == (message,)
    assert message in error.describe(403)
    assert json.loads(error.model_dump_json())["message"] == message
