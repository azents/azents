"""Docker-free subscription evidence serialization and log filtering tests."""

import datetime
import json

import pytest
from azentspublicclient.models.subscription_usage_unavailable_reason import (
    SubscriptionUsageUnavailableReason,
)
from azentspublicclient.models.subscription_usage_unavailable_response import (
    SubscriptionUsageUnavailableResponse,
)

from support.subscription_usage_evidence import (
    json_object,
    subscription_usage_log_records,
)


def test_json_object_normalizes_generated_datetime_values() -> None:
    """Serialize generated-client datetime fields without using broken to_json."""
    response = SubscriptionUsageUnavailableResponse(
        type="unavailable",
        integration_id="integration-id",
        provider="chatgpt_oauth",
        fetched_at=datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC),
        reason=SubscriptionUsageUnavailableReason.DISABLED,
        message="Enable this integration to refresh subscription usage.",
        retryable=False,
    )
    assert json_object(response.to_dict()) == {
        "type": "unavailable",
        "integration_id": "integration-id",
        "provider": "chatgpt_oauth",
        "fetched_at": "2026-07-19T00:00:00Z",
        "reason": "disabled",
        "message": "Enable this integration to refresh subscription usage.",
        "retryable": False,
    }


def test_subscription_usage_log_records_ignore_unrelated_service_logs() -> None:
    """Scope source-value checks to the subscription usage logging boundary."""
    usage_record = {
        "name": "azents.services.subscription_usage.service",
        "operation": "subscription_usage_read",
        "outcome": "available",
    }
    logs = "\n".join(
        [
            json.dumps(
                {
                    "name": "azents.core.email.service",
                    "to_email": "unrelated@example.com",
                }
            ),
            json.dumps(usage_record),
            "non-json process output",
        ]
    )
    assert subscription_usage_log_records(logs) == [usage_record]


@pytest.mark.parametrize(
    "unrelated",
    [
        None,
        False,
        0,
        "",
        [],
        {},
        {"name": None},
        {"name": False},
        {"name": 0},
        {"name": []},
        {"name": {}},
        {"name": ""},
        {"name": "azents.services.other"},
    ],
)
def test_log_source_decoder_skips_malformed_and_unrelated_records(
    unrelated: object,
) -> None:
    """Only strict source strings can select subscription usage evidence."""
    record = {"name": "azents.services.subscription_usage.service"}
    logs = "\n".join([json.dumps(unrelated), "invalid JSON", json.dumps(record)])
    assert subscription_usage_log_records(logs) == [record]


def test_log_evidence_preserves_opaque_fields_and_source_prefix_semantics() -> None:
    """Return accepted log fields exactly, without interpreting their contents."""
    records = [
        {
            "name": name,
            "message": "Subscription usage refresh failed",
            "operation": "subscription_usage_read",
            "outcome": "unavailable",
            "future_field": {
                "nested": [None, False, 0, "", {"source": "unrelated"}],
            },
            "credential": "synthetic-private-evidence",
        }
        for name in (
            "azents.services.subscription_usage",
            "azents.services.subscription_usage.service",
            "azents.services.subscription_usage_future",
        )
    ]
    logs = "\n".join(json.dumps(record) for record in records)
    assert subscription_usage_log_records(logs) == records


def test_missing_subscription_evidence_remains_a_failure() -> None:
    """Do not convert an empty or unrelated log capture into successful QA."""
    with pytest.raises(AssertionError):
        subscription_usage_log_records('{"name": null}\nnot JSON')
