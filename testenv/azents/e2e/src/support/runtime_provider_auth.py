"""Runtime Provider authentication helpers for deterministic E2E fixtures."""

import datetime
from typing import cast

import requests


class RuntimeProviderAuthenticationError(RuntimeError):
    """The supported Runtime Provider authentication flow failed."""


def issue_runtime_provider_credential(
    *,
    admin_server_url: str,
    public_server_url: str,
    admin_access_token: str,
    provider_id: str,
    subject: str,
    expires_at: datetime.datetime,
) -> str:
    """Create and rotate an Admin binding, then exchange its one-time grant."""
    authorization = {"Authorization": f"Bearer {admin_access_token}"}
    binding_response = requests.post(
        (
            f"{admin_server_url}/runtime-provider/v1/providers/{provider_id}/"
            "authentication-bindings"
        ),
        headers=authorization,
        json={
            "auth_method": "azents_issued_token",
            "subject": subject,
            "config": None,
        },
        timeout=10,
    )
    if binding_response.status_code != 201:
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider authentication binding creation failed with HTTP "
            f"{binding_response.status_code}"
        )
    binding_payload = _response_object(
        binding_response,
        operation="Runtime Provider authentication binding creation",
    )
    binding_id = binding_payload.get("id")
    admin_version = binding_payload.get("admin_version")
    if (
        not isinstance(binding_id, str)
        or not isinstance(admin_version, int)
        or isinstance(admin_version, bool)
        or admin_version < 1
    ):
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider authentication binding response was incomplete"
        )

    rotation_response = requests.post(
        (
            f"{admin_server_url}/runtime-provider/v1/authentication-bindings/"
            f"{binding_id}/rotate"
        ),
        headers=authorization,
        json={
            "expected_admin_version": admin_version,
            "expires_at": expires_at.isoformat(),
        },
        timeout=10,
    )
    if rotation_response.status_code != 200:
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider authentication binding rotation failed with HTTP "
            f"{rotation_response.status_code}"
        )
    rotation_payload = _response_object(
        rotation_response,
        operation="Runtime Provider authentication binding rotation",
    )
    grant_id = rotation_payload.get("grant_id")
    grant_secret = rotation_payload.get("secret")
    if not isinstance(grant_id, str) or not isinstance(grant_secret, str):
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider authentication binding rotation response was incomplete"
        )

    credential_response = requests.post(
        f"{public_server_url}/runtime-provider-enrollment/v1/credentials/exchange",
        json={"grant_id": grant_id, "secret": grant_secret},
        timeout=10,
    )
    if credential_response.status_code != 200:
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider credential exchange failed with HTTP "
            f"{credential_response.status_code}"
        )
    credential_payload = _response_object(
        credential_response,
        operation="Runtime Provider credential exchange",
    )
    credential = credential_payload.get("credential")
    if not isinstance(credential, str):
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider credential exchange response was incomplete"
        )
    return credential


def _response_object(
    response: requests.Response,
    *,
    operation: str,
) -> dict[str, object]:
    """Validate an HTTP response payload without retaining secret-bearing bodies."""
    payload = cast(object, response.json())
    if not isinstance(payload, dict):
        raise RuntimeProviderAuthenticationError(
            f"{operation} response was not an object"
        )
    return cast(dict[str, object], payload)
