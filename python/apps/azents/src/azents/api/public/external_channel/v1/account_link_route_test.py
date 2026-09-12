"""External account link public route tests."""

import datetime
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import CurrentUser, get_elevated_user
from azents.core.external_account_link import (
    ExternalAccountLinkCandidateCreated,
    ExternalAccountLinkCandidateStatus,
    ExternalAccountLinkConflict,
)
from azents.services.external_account_link import ExternalAccountLinkService

from .account_link_route import router


class _Service:
    """Route service double."""

    conflict = False

    async def create_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        origin_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateCreated:
        """Return a one-time candidate or a safe conflict."""
        del user_id, auth_session_id
        if self.conflict:
            raise ExternalAccountLinkConflict
        return ExternalAccountLinkCandidateCreated(
            id="candidate-1",
            origin_id=origin_id,
            code="one-time-code",
            expires_at=now + datetime.timedelta(minutes=10),
            status=ExternalAccountLinkCandidateStatus.PENDING_PROVIDER_PROOF,
        )


def _client(service: _Service) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/external-channel/v1")
    app.dependency_overrides[get_elevated_user] = lambda: CurrentUser(
        user_id="user-1",
        session_id="auth-session-1",
        elevated=True,
    )
    app.dependency_overrides[ExternalAccountLinkService] = lambda: cast(Any, service)
    return TestClient(app)


def test_candidate_create_returns_code_once_with_no_store() -> None:
    """Protect the one-time plaintext candidate response from caching."""
    response = _client(_Service()).post(
        "/external-channel/v1/account-link-origins/origin-1/candidates"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "id": "candidate-1",
        "origin_id": "origin-1",
        "code": "one-time-code",
        "expires_at": response.json()["expires_at"],
        "status": "pending_provider_proof",
    }


def test_candidate_create_returns_structured_nondisclosing_conflict() -> None:
    """Expose a stable conflict code without another owner's identity."""
    service = _Service()
    service.conflict = True
    response = _client(service).post(
        "/external-channel/v1/account-link-origins/origin-1/candidates"
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "conflict",
            "message": "This external account cannot be connected.",
        }
    }
