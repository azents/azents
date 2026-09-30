"""Scenario isolation for lightweight file-boundary model-input evidence."""

import json

from tests.required.public.test_file_upload import _scenario_model_requests


def test_scenario_model_requests_exclude_unrelated_journal_bodies() -> None:
    """Accumulated requests do not consume this scenario's evidence budget."""
    scenario = {"messages": [{"content": "unique file boundary prompt"}]}
    payload = [
        {"body": {"messages": [{"content": "unrelated history"}]}},
        {"body": scenario},
        {"body": {"messages": [{"content": "another scenario warning"}]}},
    ]
    assert _scenario_model_requests(payload, prompt="unique file boundary prompt") == [
        json.dumps(scenario, ensure_ascii=False)
    ]


def test_scenario_model_requests_cannot_borrow_another_scenarios_warning() -> None:
    """Prompt and size warning must belong to the same selected request."""
    payload = [
        {"body": {"messages": [{"content": "unique file boundary prompt"}]}},
        {"body": {"messages": [{"content": "unrelated size warning"}]}},
    ]
    selected = _scenario_model_requests(payload, prompt="unique file boundary prompt")
    assert len(selected) == 1
    assert "size warning" not in selected[0]
