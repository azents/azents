"""Runtime Provider enrollment v1 Public API tests."""

import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute

from azents.api.public.runtime_provider_enrollment.v1 import (
    exchange_credential,
    mount,
)
from azents.api.public.runtime_provider_enrollment.v1.data import (
    RuntimeProviderCredentialExchangeRequest,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialIssued,
    RuntimeProviderEnrollmentUnavailable,
)
from azents.utils.fastapi.route import as_route_mounter


class FakeEnrollmentService:
    """Return configured enrollment outcomes for route tests."""

    def __init__(
        self,
        *,
        issued: RuntimeProviderCredentialIssued | None,
    ) -> None:
        self.issued = issued

    async def exchange_grant(
        self,
        *,
        grant_id: str,
        secret: str,
        credential_expires_at: datetime.datetime | None,
    ) -> RuntimeProviderCredentialIssued:
        """Return a credential or reject the grant without exposing its state."""
        assert grant_id == "grant-1"
        assert secret == "grant-secret"
        assert credential_expires_at is None
        if self.issued is None:
            raise RuntimeProviderEnrollmentUnavailable("grant_unavailable")
        return self.issued


def test_mounts_operator_exchange_route() -> None:
    """Expose the operator grant exchange route without workspace authentication."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert "/runtime-provider-enrollment/v1/credentials/exchange" in paths


@pytest.mark.asyncio
async def test_exchange_returns_one_time_provider_credential() -> None:
    """Return only the credential output needed to configure the controller."""
    response = await exchange_credential(
        service=FakeEnrollmentService(
            issued=RuntimeProviderCredentialIssued(
                credential_id="credential-1",
                provider_id="provider-1",
                secret="provider-credential",
                expires_at=None,
            )
        ),
        request_body=RuntimeProviderCredentialExchangeRequest(
            grant_id="grant-1",
            secret="grant-secret",
        ),
    )

    assert response.credential_id == "credential-1"
    assert response.provider_id == "provider-1"
    assert response.credential == "provider-credential"
    assert response.expires_at is None


@pytest.mark.asyncio
async def test_exchange_hides_grant_failure_reason() -> None:
    """Normalize invalid grant outcomes to one generic operator response."""
    with pytest.raises(HTTPException) as error:
        await exchange_credential(
            service=FakeEnrollmentService(issued=None),
            request_body=RuntimeProviderCredentialExchangeRequest(
                grant_id="grant-1",
                secret="grant-secret",
            ),
        )

    assert error.value.status_code == 403
    assert error.value.detail == "Provider enrollment grant is invalid or unavailable."
