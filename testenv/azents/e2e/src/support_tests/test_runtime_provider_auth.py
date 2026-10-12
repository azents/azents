"""Tests for deterministic Runtime Provider authentication support."""

import datetime
import json
import traceback
from unittest.mock import Mock

import pytest
import requests

from support import runtime_provider_auth


def _response(
    status_code: int,
    payload: object,
) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    return response


def test_issues_credential_through_current_binding_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use Admin binding creation/rotation before the public grant exchange."""
    post = Mock(
        side_effect=[
            _response(201, {"id": "binding-1", "admin_version": 1}),
            _response(200, {"grant_id": "grant-1", "secret": "grant-secret"}),
            _response(200, {"credential": "provider-credential"}),
        ]
    )
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    expires_at = datetime.datetime(2026, 7, 24, 2, tzinfo=datetime.UTC)

    credential = runtime_provider_auth.issue_runtime_provider_credential(
        admin_server_url="http://admin",
        public_server_url="http://public",
        admin_access_token="admin-token",
        provider_id="system-docker",
        subject="e2e:provider-resource-1",
        expires_at=expires_at,
    )

    assert credential == "provider-credential"
    assert post.call_count == 3
    create_call, rotate_call, exchange_call = post.call_args_list
    assert create_call.args == (
        "http://admin/runtime-provider/v1/providers/system-docker/"
        "authentication-bindings",
    )
    assert create_call.kwargs["json"] == {
        "auth_method": "azents_issued_token",
        "subject": "e2e:provider-resource-1",
        "config": None,
    }
    assert rotate_call.args == (
        "http://admin/runtime-provider/v1/authentication-bindings/binding-1/rotate",
    )
    assert rotate_call.kwargs["json"] == {
        "expected_admin_version": 1,
        "expires_at": expires_at.isoformat(),
    }
    assert exchange_call.args == (
        "http://public/runtime-provider-enrollment/v1/credentials/exchange",
    )
    assert exchange_call.kwargs["json"] == {
        "grant_id": "grant-1",
        "secret": "grant-secret",
    }


def test_rejects_incomplete_binding_without_rotating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop before issuing a grant when the safe binding projection is incomplete."""
    post = Mock(side_effect=[_response(201, {"id": "binding-1"})])
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)

    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="binding response was incomplete",
    ):
        runtime_provider_auth.issue_runtime_provider_credential(
            admin_server_url="http://admin",
            public_server_url="http://public",
            admin_access_token="admin-token",
            provider_id="system-docker",
            subject="e2e:provider-resource-1",
            expires_at=datetime.datetime(2026, 7, 24, 2, tzinfo=datetime.UTC),
        )

    assert post.call_count == 1


def _issue() -> str:
    return runtime_provider_auth.issue_runtime_provider_credential(
        admin_server_url="http://admin",
        public_server_url="http://public",
        admin_access_token="admin-token",
        provider_id="system-docker",
        subject="e2e:provider-resource-1",
        expires_at=datetime.datetime(2026, 7, 24, 2, tzinfo=datetime.UTC),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"id": None, "admin_version": 1},
        {"id": 3, "admin_version": 1},
        {"id": True, "admin_version": 1},
        {"id": "binding-1", "admin_version": None},
        {"id": "binding-1", "admin_version": True},
        {"id": "binding-1", "admin_version": "1"},
        {"id": "binding-1", "admin_version": 1.0},
        {"id": "binding-1", "admin_version": 0},
        {"id": "binding-1", "admin_version": -1},
    ],
)
def test_invalid_binding_projection_never_rotates(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    post = Mock(return_value=_response(201, payload))
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="binding response was incomplete",
    ):
        _issue()
    assert post.call_count == 1


@pytest.mark.parametrize("field", ["grant_id", "secret"])
@pytest.mark.parametrize("value", [None, 3, True, [], {}])
def test_invalid_rotation_projection_never_exchanges(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    payload = {"grant_id": "grant-1", "secret": "private-grant-secret", field: value}
    post = Mock(
        side_effect=[
            _response(201, {"id": "binding-1", "admin_version": 1}),
            _response(200, payload),
        ]
    )
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="rotation response was incomplete",
    ) as failure:
        _issue()
    assert post.call_count == 2
    assert "private-grant-secret" not in "".join(
        traceback.format_exception(failure.value)
    )


@pytest.mark.parametrize("value", [None, 3, True, [], {}])
def test_invalid_credential_projection_stays_a_safe_failure(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    post = Mock(
        side_effect=[
            _response(201, {"id": "binding-1", "admin_version": 1}),
            _response(200, {"grant_id": "grant-1", "secret": "private-grant-secret"}),
            _response(200, {"credential": value, "private_metadata": "private-body"}),
        ]
    )
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="exchange response was incomplete",
    ) as failure:
        _issue()
    assert post.call_count == 3
    diagnostic = "".join(traceback.format_exception(failure.value))
    assert "private-grant-secret" not in diagnostic
    assert "private-body" not in diagnostic


@pytest.mark.parametrize("phase", [0, 1, 2])
@pytest.mark.parametrize("payload", [None, [], "private-body"])
def test_non_object_success_response_fails_at_its_operation_boundary(
    monkeypatch: pytest.MonkeyPatch, phase: int, payload: object
) -> None:
    responses = [
        _response(201, {"id": "binding-1", "admin_version": 1}),
        _response(200, {"grant_id": "grant-1", "secret": "private-grant-secret"}),
        _response(200, {"credential": "private-credential"}),
    ]
    responses[phase].json.return_value = payload
    post = Mock(side_effect=responses)
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="response was not an object",
    ) as failure:
        _issue()
    assert post.call_count == phase + 1
    assert "private-body" not in "".join(traceback.format_exception(failure.value))


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_invalid_json_never_exposes_response_body(
    monkeypatch: pytest.MonkeyPatch, phase: int
) -> None:
    responses = [
        _response(201, {"id": "binding-1", "admin_version": 1}),
        _response(200, {"grant_id": "grant-1", "secret": "private-grant-secret"}),
        _response(200, {"credential": "private-credential"}),
    ]
    responses[phase].json.side_effect = json.JSONDecodeError(
        "private-error", "private-response-body", 0
    )
    post = Mock(side_effect=responses)
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    with pytest.raises(
        runtime_provider_auth.RuntimeProviderAuthenticationError,
        match="response was not valid JSON",
    ) as failure:
        _issue()
    assert post.call_count == phase + 1
    diagnostic = "".join(traceback.format_exception(failure.value))
    assert "private-error" not in diagnostic
    assert "private-response-body" not in diagnostic


def test_complete_current_wire_shape_accepts_uninterpreted_api_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project only fields used by this operation, retaining API compatibility."""
    binding = {
        "id": "binding-1",
        "provider_id": "system-docker",
        "auth_method": "azents_issued_token",
        "subject": "e2e:provider-resource-1",
        "state": "active",
        "owner": "admin",
        "bootstrap_declaration_id": None,
        "config": None,
        "admin_version": 3,
        "connected": False,
        "last_authenticated_at": None,
        "last_connected_at": None,
        "revoked_at": None,
        "revoked_by_user_id": None,
        "revocation_reason": None,
        "created_at": "2026-07-24T01:00:00Z",
        "updated_at": "2026-07-24T01:00:00Z",
        "future_extension": {"opaque": "retained-by-api"},
    }
    post = Mock(
        side_effect=[
            _response(201, binding),
            _response(
                200,
                {
                    "binding": binding,
                    "grant_id": "grant-1",
                    "secret": "grant-secret",
                    "expires_at": "2026-07-24T02:00:00Z",
                    "future_extension": None,
                },
            ),
            _response(
                200,
                {
                    "credential_id": "credential-1",
                    "provider_id": "system-docker",
                    "credential": "provider-credential",
                    "expires_at": None,
                    "future_extension": ["opaque"],
                },
            ),
        ]
    )
    monkeypatch.setattr(runtime_provider_auth.requests, "post", post)
    assert _issue() == "provider-credential"
    assert post.call_args_list[1].kwargs["json"]["expected_admin_version"] == 3
    assert post.call_args_list[2].kwargs["json"] == {
        "grant_id": "grant-1",
        "secret": "grant-secret",
    }
