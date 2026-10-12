"""Runtime Provider authentication helpers for deterministic E2E fixtures."""

import datetime

import requests
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError


class RuntimeProviderAuthenticationError(RuntimeError):
    """The supported Runtime Provider authentication flow failed."""


class _AuthenticationResponse(BaseModel):
    """Project interpreted fields while accepting forward-compatible API fields."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class _BindingResponse(_AuthenticationResponse):
    """The safe identity and optimistic version needed for the next API request."""

    id: StrictStr
    admin_version: StrictInt = Field(gt=0)


class _RotationResponse(_AuthenticationResponse):
    """The one-time grant fields issued by the rotation operation."""

    grant_id: StrictStr
    secret: StrictStr


class _CredentialResponse(_AuthenticationResponse):
    """The enrolled credential issued by the public exchange operation."""

    credential: StrictStr


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
    binding = _decode_response(
        binding_response,
        _BindingResponse,
        operation="Runtime Provider authentication binding creation",
        incomplete="Runtime Provider authentication binding response was incomplete",
    )

    rotation_response = requests.post(
        (
            f"{admin_server_url}/runtime-provider/v1/authentication-bindings/"
            f"{binding.id}/rotate"
        ),
        headers=authorization,
        json={
            "expected_admin_version": binding.admin_version,
            "expires_at": expires_at.isoformat(),
        },
        timeout=10,
    )
    if rotation_response.status_code != 200:
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider authentication binding rotation failed with HTTP "
            f"{rotation_response.status_code}"
        )
    rotation = _decode_response(
        rotation_response,
        _RotationResponse,
        operation="Runtime Provider authentication binding rotation",
        incomplete=(
            "Runtime Provider authentication binding rotation response was incomplete"
        ),
    )

    credential_response = requests.post(
        f"{public_server_url}/runtime-provider-enrollment/v1/credentials/exchange",
        json={"grant_id": rotation.grant_id, "secret": rotation.secret},
        timeout=10,
    )
    if credential_response.status_code != 200:
        raise RuntimeProviderAuthenticationError(
            "Runtime Provider credential exchange failed with HTTP "
            f"{credential_response.status_code}"
        )
    credential = _decode_response(
        credential_response,
        _CredentialResponse,
        operation="Runtime Provider credential exchange",
        incomplete="Runtime Provider credential exchange response was incomplete",
    )
    return credential.credential


def _decode_response[ResponseT: BaseModel](
    response: requests.Response,
    model: type[ResponseT],
    *,
    operation: str,
    incomplete: str,
) -> ResponseT:
    """Validate an operation projection without exposing secret-bearing errors."""
    try:
        payload: object = response.json()
    except ValueError:
        raise RuntimeProviderAuthenticationError(
            f"{operation} response was not valid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise RuntimeProviderAuthenticationError(
            f"{operation} response was not an object"
        )
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise RuntimeProviderAuthenticationError(incomplete) from None
