"""Retry-policy decoding compatibility without database effects."""

from collections.abc import Mapping

import pytest

from azents.repos.llm_catalog.data import CatalogRetryPolicy


@pytest.mark.parametrize(
    ("diagnostics", "blocked"),
    [
        (None, False),
        ({}, False),
        ({"other_diagnostic": True}, False),
        ({"automatic_retry_blocked": None}, False),
        ({"automatic_retry_blocked": False}, False),
        ({"automatic_retry_blocked": True}, True),
        ({"automatic_retry_blocked": 1}, False),
        ({"automatic_retry_blocked": "true"}, False),
        ({"automatic_retry_blocked": []}, False),
    ],
)
def test_retry_policy_retains_literal_true_marker(
    diagnostics: Mapping[str, object] | None,
    blocked: bool,
) -> None:
    """Legacy, absent and malformed markers retain the existing scheduling outcome."""
    policy = CatalogRetryPolicy.from_diagnostics(diagnostics)
    assert policy.automatic_retry_blocked is blocked
