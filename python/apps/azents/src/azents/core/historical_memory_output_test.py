"""Historical Memory model output tests."""

import pytest
from pydantic import ValidationError

from azents.core.historical_memory_output import HistoricalMemorySummaryOutput


def test_summary_output_accepts_empty_success() -> None:
    """An empty string distinguishes successful no-useful-context output."""
    output = HistoricalMemorySummaryOutput.model_validate_json('{"summary":""}')

    assert output.summary == ""


def test_summary_output_rejects_additional_fields() -> None:
    """The extraction contract contains only the summary body."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HistoricalMemorySummaryOutput.model_validate_json(
            '{"summary":"context","slug":"invented"}'
        )
