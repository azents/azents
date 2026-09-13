"""Safe failure-output tests for provider OAuth evidence."""

import json

import pytest

from support.browser_artifact_safety import sanitize_browser_artifact
from tests.required.public.external_account_linking_scenarios import (
    _require_sanitized_evidence,
)


def test_oauth_evidence_failure_does_not_echo_the_secret() -> None:
    """Keep synthetic OAuth material out of pytest failure text."""
    sentinel = "synthetic-private-oauth-state"
    with pytest.raises(AssertionError) as failure:
        _require_sanitized_evidence(
            f"provider evidence accidentally contained {sentinel}",
            (sentinel,),
        )
    rendered_failure = str(failure.value)
    if sentinel in rendered_failure:
        raise AssertionError("Safe evidence failure echoed OAuth material.")
    if rendered_failure != (
        "Sanitized provider evidence exposed OAuth secret material."
    ):
        raise AssertionError("Safe evidence failure category changed.")


def test_browser_failure_artifacts_redact_oauth_callback_values() -> None:
    """Captured callback HTML cannot retain code or state query values."""
    content = (
        '<script src="/oauth/external-account/slack/callback?'
        'code=sentinel-code&amp;state=sentinel-state"></script>'
        r'<script>"/oauth/external-account/slack/callback?code=encoded-code\u0026state=encoded-state"</script>'
        r'<script>"/callback%3Fcode%3Dpercent-code%26state%3Dpercent-state"</script>'
    )

    sanitized = sanitize_browser_artifact(content)

    for sentinel in (
        "sentinel-code",
        "sentinel-state",
        "encoded-code",
        "encoded-state",
        "percent-code",
        "percent-state",
    ):
        assert sentinel not in sanitized
    assert sanitized.count("<redacted>") == 6


def test_browser_failure_artifacts_redact_next_flight_callback_values() -> None:
    """Captured Next Flight segments cannot retain structured callback values."""
    page_segment = "__PAGE__?" + json.dumps(
        {"code": "flight-code", "state": "flight-state"},
        separators=(",", ":"),
    )
    flight_record = json.dumps([1, page_segment], separators=(",", ":"))
    inline_script = json.dumps(flight_record, separators=(",", ":"))
    content = (
        f"<script>{page_segment}</script>"
        f"<script>{flight_record}</script>"
        f"<script>{inline_script}</script>"
    )

    sanitized = sanitize_browser_artifact(content)

    for sentinel in (
        "flight-code",
        "flight-state",
    ):
        assert sentinel not in sanitized
    assert sanitized.count("<redacted>") == 6
