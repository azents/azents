"""Docker-free subscription evidence serialization and log filtering tests."""

import datetime
import json

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
