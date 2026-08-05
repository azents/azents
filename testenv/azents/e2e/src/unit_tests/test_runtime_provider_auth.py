"""Tests for deterministic Runtime Provider authentication support."""

import datetime
from unittest.mock import Mock

import pytest
import requests

from support import runtime_provider_auth


def _response(
    status_code: int,
    payload: dict[str, object],
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
