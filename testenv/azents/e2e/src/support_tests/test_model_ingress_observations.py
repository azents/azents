"""Listener-free regressions for interpreted model/upload/usage observations."""

import json
from datetime import datetime

import pytest
import requests
from azentspublicclient.models import (
    response_llm_provider_integration_v1_get_subscription_usage as usage_response,
)
from pydantic import ValidationError

from tests.required.public import test_file_upload as upload
from tests.required.public import test_model_selection as selection
from tests.required.public import test_subscription_usage as usage
from tests.required.public import test_xai_image_generation as xai

_UsageResult = usage_response.ResponseLlmProviderIntegrationV1GetSubscriptionUsage


def test_upload_attachment_preserves_opaque_metadata_and_content() -> None:
    payload = {
        "content": "Uploaded files",
        "attachments": [
            {
                "uri": "exchange://opaque",
                "media_type": "text/plain",
                "future": {"kept": True},
            }
        ],
        "future_message": {"kept": True},
    }
    decoded = upload._MessagePayload.model_validate(payload)
    assert decoded.attachments[0].uri == "exchange://opaque"
    assert decoded.model_dump(exclude_unset=True) == payload
    assert upload._MessagePayload(content="plain").attachments == []


@pytest.mark.parametrize("field", ["uri", "media_type"])
@pytest.mark.parametrize("bad", [None, 1, True, []])
def test_upload_attachment_rejects_malformed_interpreted_metadata(
    field: str, bad: object
) -> None:
    payload: dict[str, object] = {
        "uri": "exchange://opaque",
        "media_type": "text/plain",
    }
    payload[field] = bad
    with pytest.raises(ValidationError):
        upload._AttachmentObservation.model_validate(payload)


def test_model_tools_preserve_native_shapes_extensions_and_omission() -> None:
    payload = {
        "tools": [
            {"name": "image_generation", "future": {"kept": True}},
            {
                "type": "function",
                "function": {"name": "search", "parameters": {"type": "object"}},
            },
        ],
        "provider_extension": {"kept": True},
    }
    decoded = xai._ModelRequestObservation.model_validate(payload)
    assert [xai._tool_name(tool) for tool in decoded.tools] == [
        "image_generation",
        "search",
    ]
    assert decoded.model_dump(exclude_unset=True) == payload
    assert xai._ModelRequestObservation.model_validate({}).tools == []
    assert (
        xai._tool_name(xai._ToolDeclaration.model_validate({"type": "web_search"}))
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"tools": None},
        {"tools": [{}], "future": 1},
        {"tools": [{"function": {"name": 7}}]},
    ],
)
def test_model_tools_validate_declared_fields_without_rejecting_extensions(
    payload: dict[str, object],
) -> None:
    if payload == {"tools": [{}], "future": 1}:
        assert xai._ModelRequestObservation.model_validate(payload).model_extra == {
            "future": 1
        }
    else:
        with pytest.raises(ValidationError):
            xai._ModelRequestObservation.model_validate(payload)


def _image_result() -> dict[str, object]:
    return {
        "name": "image_generation",
        "status": "completed",
        "output": [
            {
                "type": "file",
                "kind": "image",
                "model_file_id": "model-file",
                "provider_extension": True,
            },
            {
                "type": "attachment",
                "attachment_id": "attachment",
                "media_type": "image/png",
                "size": 10,
                "availability": "available",
                "future": {"kept": True},
            },
        ],
        "future_result": True,
    }


def test_image_result_projects_parts_without_losing_redaction_evidence() -> None:
    payload = _image_result()
    decoded = xai._ImageToolResult.model_validate(payload)
    assert isinstance(decoded.output[0], xai._FilePart)
    assert isinstance(decoded.output[1], xai._AttachmentPart)
    assert decoded.output[1].attachment_id == "attachment"
    assert decoded.model_dump(exclude_unset=True) == payload
    failed = {
        "status": "failed",
        "output": [{"type": "text", "text": "Reconnect required"}],
    }
    assert (
        xai._ImageToolResult.model_validate(failed).model_dump(exclude_unset=True)
        == failed
    )


@pytest.mark.parametrize(
    "field", ["attachment_id", "media_type", "size", "availability"]
)
def test_image_result_requires_existing_asserted_wire_fields(field: str) -> None:
    attachment: dict[str, object] = {
        "type": "attachment",
        "attachment_id": "attachment",
        "media_type": "image/png",
        "size": 10,
        "availability": "available",
    }
    del attachment[field]
    with pytest.raises(ValidationError):
        xai._ImageToolResult.model_validate({"output": [attachment]})


@pytest.mark.parametrize("invalid", [True, "10", None])
def test_image_attachment_size_is_not_coerced(invalid: object) -> None:
    with pytest.raises(ValidationError):
        xai._AttachmentPart.model_validate(
            {
                "type": "attachment",
                "attachment_id": "a",
                "media_type": "image/png",
                "size": invalid,
                "availability": "available",
            }
        )


def _usage_journal() -> dict[str, object]:
    return {
        "scenario": "xai_normal",
        "path": "/v1/billing",
        "sequence": 1,
        "status": 200,
        "required_headers": {"authorization": True},
    }


def test_usage_journal_preserves_exact_wire_and_safety_checks() -> None:
    payload = _usage_journal()
    decoded = usage._USAGE_JOURNAL.validate_python([payload])
    assert decoded[0].path == "/v1/billing"
    assert decoded[0].sequence == 1
    assert decoded[0].model_dump() == payload
    usage._assert_safe_subscription_usage_journal(decoded)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("sequence", True),
        ("status", "200"),
        ("path", None),
        ("required_headers", {"authorization": "true"}),
        ("unknown", "opaque"),
    ],
)
def test_usage_journal_rejects_malformed_or_unexpected_operational_fields(
    field: str, bad: object
) -> None:
    payload = _usage_journal()
    payload[field] = bad
    with pytest.raises(ValidationError):
        usage._USAGE_JOURNAL.validate_python([payload])


def test_usage_journal_does_not_hide_sensitive_extension_evidence() -> None:
    payload = _usage_journal()
    payload["path"] = "test-chatgpt-access-token"
    with pytest.raises(AssertionError):
        usage._assert_safe_subscription_usage_journal(
            usage._USAGE_JOURNAL.validate_python([payload])
        )


def test_catalog_sync_retains_wire_extensions_for_assertions() -> None:
    payload = {
        "status": "succeeded",
        "started_at": "2026-10-14T00:00:00Z",
        "finished_at": None,
        "failure_code": None,
        "failure_message": None,
        "fetched_count": 1,
        "matched_count": 1,
        "hidden_count": 0,
        "skipped_count": 0,
        "action_hint": None,
        "id": "unexpected-id",
        "future": {"kept": True},
    }
    decoded = selection._CatalogSyncObservation.model_validate(payload)
    assert decoded.status == "succeeded"
    assert "id" in decoded.model_dump()
    assert decoded.model_extra == {"id": "unexpected-id", "future": {"kept": True}}


def test_catalog_wait_and_rename_decode_equal_sync_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = {
        "status": "succeeded",
        "started_at": "2026-10-14T00:00:00Z",
        "finished_at": None,
        "failure_code": None,
        "failure_message": None,
        "fetched_count": 1,
        "matched_count": 1,
        "hidden_count": 0,
        "skipped_count": 0,
        "action_hint": None,
        "future": {"kept": True},
    }
    catalog = {
        "catalog_id": "catalog",
        "catalog_scope": "integration",
        "last_success_at": None,
        "latest_sync": sync,
        "stale": False,
        "sync_available_at": None,
        "automatic_retry_blocked": False,
        "entries": [],
        "total": 0,
        "limit": 10,
        "offset": 0,
    }
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(catalog).encode()
    monkeypatch.setattr(selection.requests, "get", lambda *_args, **_kwargs: response)
    initial = selection._wait_for_initial_catalog_sync(
        "http://unused.invalid", "token", "workspace", "integration"
    )
    renamed = selection._CatalogObservation.model_validate(response.json())
    assert initial.latest_sync is not None
    assert type(initial.latest_sync) is type(renamed.latest_sync)
    assert initial.latest_sync == renamed.latest_sync
    sync["future"] = {"kept": False}
    assert (
        selection._CatalogObservation.model_validate(catalog).latest_sync
        != initial.latest_sync
    )


@pytest.mark.parametrize(
    "model,payload",
    [
        (
            selection._ModalitiesObservation,
            {"input": ["text", "image"], "output": ["text"]},
        ),
        (
            selection._ContextWindowObservation,
            {
                "default_input_tokens": None,
                "max_input_tokens": 512_000,
                "max_output_tokens": 16_000,
            },
        ),
    ],
)
def test_catalog_literal_equality_retains_extensions_and_explicit_null(
    model: type[selection._ModalitiesObservation]
    | type[selection._ContextWindowObservation],
    payload: dict[str, object],
) -> None:
    original = model.model_validate(payload)
    assert original.model_dump(mode="json", exclude_unset=True) == payload
    extended = {**payload, "future": {"kept": True}}
    observation = model.model_validate(extended)
    assert observation.model_dump(mode="json", exclude_unset=True) == extended
    assert observation.model_dump(mode="json", exclude_unset=True) != payload


class _GeneratedUsageApi:
    """Inject generated SDK results while executing the real usage assertions."""

    def llm_provider_integration_v1_get_subscription_usage(
        self,
        *,
        integration_id: str,
        handle: str,
        _headers: dict[str, str],
    ) -> usage_response.ResponseLlmProviderIntegrationV1GetSubscriptionUsage:
        assert handle == "workspace"
        assert _headers["Authorization"] in {"Bearer owner", "Bearer member"}
        if integration_id == "test-chatgpt-transport":
            return _UsageResult.from_dict(
                {
                    "type": "unavailable",
                    "integration_id": "1" * 32,
                    "provider": "chatgpt_oauth",
                    "fetched_at": "2026-10-14T00:00:00Z",
                    "reason": "temporarily_unavailable",
                    "message": "Usage is temporarily unavailable.",
                    "retryable": True,
                }
            )
        financials = {
            "type": "chatgpt",
            "has_credits": True,
            "unlimited": False,
            "balance": "120 credits",
            "spend_limit": "500 credits",
            "spend_used": "180 credits",
            "spend_remaining_percent": 64.0,
            "spend_resets_at": "2026-08-01T00:00:00Z",
            "reached_type": None,
        }
        limits = [
            {
                "id": "primary",
                "label": "Primary window",
                "used_percent": (
                    100.0 if integration_id == "test-chatgpt-exhausted" else 35.0
                ),
                "window_minutes": 300,
                "resets_at": "2026-08-01T00:00:00Z",
                "primary": True,
            },
            {
                "id": "secondary",
                "label": "Secondary window",
                "used_percent": 81.0,
                "window_minutes": 10080,
                "resets_at": None,
                "primary": False,
            },
        ]
        return _UsageResult.from_dict(
            {
                "type": "available",
                "integration_id": "1" * 32,
                "provider": "chatgpt_oauth",
                "fetched_at": "2026-10-14T00:00:00Z",
                "plan_label": "Pro",
                "limits": limits,
                "financial_details": (
                    None if _headers["Authorization"] == "Bearer member" else financials
                ),
            }
        )


def _inject_generated_usage_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only external setup/API transports, not the assertion/egress code."""
    workspace = usage.SubscriptionWorkspace(
        handle="workspace",
        owner_email="owner@example.invalid",
        owner_token="owner",
        member_token="member",
    )
    monkeypatch.setattr(usage, "setup_subscription_workspace", lambda *_args: workspace)
    monkeypatch.setattr(
        usage,
        "create_chatgpt_subscription_integration",
        lambda *_args, **kwargs: kwargs["scenario"],
    )
    monkeypatch.setattr(
        usage, "LLMProviderIntegrationV1Api", lambda _client: _GeneratedUsageApi()
    )
    monkeypatch.setattr(usage, "clear_subscription_usage_journal", lambda _url: None)
    monkeypatch.setattr(usage, "subscription_usage_journal", lambda _url: [])


def test_actual_owner_member_financial_assertions_serialize_generated_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inject_generated_usage_boundary(monkeypatch)
    usage.TestChatGPTSubscriptionUsage().test_owner_member_and_exhausted_snapshots(
        public_api_client=usage.azentspublicclient.ApiClient(),
        admin_api_client=usage.azentsadminclient.ApiClient(),
        openai_proxy_url="http://unused.invalid",
    )


def test_actual_unavailable_wire_assertion_serializes_generated_fetched_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _inject_generated_usage_boundary(monkeypatch)
    usage.TestChatGPTSubscriptionUsage().test_transport_failure_reaches_public_unavailable_result(
        public_api_client=usage.azentspublicclient.ApiClient(),
        admin_api_client=usage.azentsadminclient.ApiClient(),
        openai_proxy_url="http://unused.invalid",
    )


def test_usage_json_egress_retains_dates_nulls_extensions_and_sensitive_evidence() -> (
    None
):
    api = _GeneratedUsageApi()
    owner = api.llm_provider_integration_v1_get_subscription_usage(
        integration_id="test-chatgpt-normal",
        handle="workspace",
        _headers={"Authorization": "Bearer owner"},
    ).actual_instance
    assert isinstance(owner, usage.SubscriptionUsageAvailableResponse)
    assert isinstance(owner.fetched_at, datetime)
    owner.additional_properties["future"] = {"date": owner.fetched_at, "kept": True}
    wire = usage._json_object(owner.to_dict())
    assert wire["fetched_at"] == "2026-10-14T00:00:00Z"
    assert wire["future"] == {"date": "2026-10-14T00:00:00Z", "kept": True}
    financials = wire["financial_details"]
    assert isinstance(financials, dict)
    assert financials["spend_resets_at"] == "2026-08-01T00:00:00Z"
    assert "reached_type" in financials and financials["reached_type"] is None
    usage._assert_no_sensitive_source_values(owner)
    member = api.llm_provider_integration_v1_get_subscription_usage(
        integration_id="test-chatgpt-normal",
        handle="workspace",
        _headers={"Authorization": "Bearer member"},
    ).actual_instance
    assert isinstance(member, usage.SubscriptionUsageAvailableResponse)
    assert usage._json_object(member.to_dict())["financial_details"] is None
    owner.additional_properties["sensitive_extension"] = "test-chatgpt-access-token"
    with pytest.raises(AssertionError):
        usage._assert_no_sensitive_source_values(owner)
