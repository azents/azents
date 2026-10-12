"""Pure bounded Slack history configuration without provider resources."""

import pytest

from support.slack_provider_fake import FakeState


@pytest.mark.parametrize(
    "payload",
    [
        {"history_scenario_sequence": []},
        {"history_scenario_sequence": ["ok"] * 11},
        {"history_retry_after_seconds": []},
        {"history_retry_after_seconds": [1] * 11},
        {"history_retry_after_seconds": [0]},
        {"history_retry_after_seconds": [301]},
    ],
)
def test_slack_fake_rejects_unbounded_history_sequences(
    payload: dict[str, object],
) -> None:
    """Reject fixture sequences that exceed deterministic test bounds."""
    with pytest.raises(ValueError):
        FakeState().configure(payload)
