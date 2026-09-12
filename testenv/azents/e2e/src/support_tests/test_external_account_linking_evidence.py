"""Safe failure-output tests for External Account linking evidence."""

import pytest

from tests.required.public.external_account_linking_scenarios import (
    _require_sanitized_evidence,
)


def test_secret_evidence_failure_does_not_echo_the_secret() -> None:
    """Keep a redaction regression secret out of pytest failure text."""
    sentinel = "synthetic-private-link-code"
    with pytest.raises(AssertionError) as failure:
        _require_sanitized_evidence(
            f"provider evidence accidentally contained {sentinel}",
            (sentinel,),
        )
    rendered_failure = str(failure.value)
    if sentinel in rendered_failure:
        raise AssertionError("Safe evidence failure echoed secret material.")
    if rendered_failure != (
        "Sanitized provider evidence exposed transient secret material."
    ):
        raise AssertionError("Safe evidence failure category changed.")
