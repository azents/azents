"""Provider authentication verifier unit tests."""

import base64
import datetime
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client.api.authentication_v1_api import AuthenticationV1Api
from kubernetes_asyncio.client.models.v1_token_review import V1TokenReview
from kubernetes_asyncio.client.models.v1_token_review_spec import V1TokenReviewSpec
from kubernetes_asyncio.client.models.v1_token_review_status import V1TokenReviewStatus
from kubernetes_asyncio.client.models.v1_user_info import V1UserInfo
from kubernetes_asyncio.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBinding
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.services.runtime_provider_control.data import (
    KubernetesServiceAccountTokenReview,
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)
from azents.services.runtime_provider_control.provider_auth import (
    KubernetesApiTokenReviewer,
    KubernetesServiceAccountProviderAuthVerifier,
    ProviderAuthRegistry,
)

_NOW = datetime.datetime(2026, 7, 23, 12, 0, tzinfo=datetime.UTC)
_SUBJECT = "system:serviceaccount:azents-runtime:provider"


@dataclass
class _Verifier:
    """Record explicit verifier dispatches."""

    method: RuntimeProviderAuthMethod
    result: RuntimeProviderCredentialAuthentication
    calls: list[str] = field(default_factory=list)

    async def verify(
        self,
        *,
        secret: str,
        now: datetime.datetime,
    ) -> RuntimeProviderCredentialAuthentication:
        self.calls.append(secret)
        assert now == _NOW
        return self.result


@dataclass(frozen=True)
class _TokenReviewer:
    """Return one deterministic TokenReview projection."""

    result: KubernetesServiceAccountTokenReview

    async def review(
        self,
        *,
        token: str,
        audience: str,
    ) -> KubernetesServiceAccountTokenReview:
        assert token == "service-account-token"
        assert audience == "azents-runtime-control"
        return self.result


@asynccontextmanager
async def _session_context(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    yield session


def _session_manager(session: AsyncSession) -> SessionManager[AsyncSession]:
    return lambda: _session_context(session)


def _authentication(
    method: RuntimeProviderAuthMethod,
) -> RuntimeProviderCredentialAuthentication:
    return RuntimeProviderCredentialAuthentication(
        binding_id="binding-1",
        credential_id=(
            "credential-1"
            if method is RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN
            else None
        ),
        provider_id="provider-1",
        provider_kind=RuntimeProviderKind.KUBERNETES,
        provider_scope=RuntimeProviderScope.SYSTEM,
        provider_workspace_id=None,
        auth_method=method,
        auth_subject=_SUBJECT,
        evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    ("method", "credential_id", "evidence_expires_at"),
    (
        (RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN, None, None),
        (
            RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            "credential-1",
            _NOW + datetime.timedelta(minutes=5),
        ),
        (RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT, None, None),
    ),
)
def test_authentication_rejects_method_specific_evidence_mismatch(
    method: RuntimeProviderAuthMethod,
    credential_id: str | None,
    evidence_expires_at: datetime.datetime | None,
) -> None:
    with pytest.raises(ValueError):
        RuntimeProviderCredentialAuthentication(
            binding_id="binding-1",
            credential_id=credential_id,
            provider_id="provider-1",
            provider_kind=RuntimeProviderKind.KUBERNETES,
            provider_scope=RuntimeProviderScope.SYSTEM,
            provider_workspace_id=None,
            auth_method=method,
            auth_subject=_SUBJECT,
            evidence_expires_at=evidence_expires_at,
        )


def _jwt(*, expires_at: datetime.datetime) -> str:
    header = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expires_at.timestamp()}).encode())
        .decode()
        .rstrip("=")
    )
    return f"{header}.{payload}.signature"


def _kubernetes_binding() -> RuntimeProviderAuthBinding:
    return RuntimeProviderAuthBinding(
        id="binding-1",
        provider_id="provider-row-1",
        auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
        subject=_SUBJECT,
        state=RuntimeProviderBindingState.ACTIVE,
        owner=RuntimeProviderBindingOwner.BOOTSTRAP,
        bootstrap_declaration_id="declaration-1",
        config={
            "namespace": "azents-runtime",
            "service_account_name": "provider",
            "audience": "azents-runtime-control",
        },
        admin_version=1,
        last_authenticated_at=None,
        last_connected_at=None,
        revoked_at=None,
        revoked_by_user_id=None,
        revocation_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _kubernetes_provider() -> RuntimeProvider:
    return RuntimeProvider(
        id="provider-row-1",
        provider_id="system-kubernetes",
        scope=RuntimeProviderScope.SYSTEM,
        workspace_id=None,
        kind=RuntimeProviderKind.KUBERNETES,
        display_name="Kubernetes",
        registration_method=RuntimeProviderRegistrationMethod.BOOTSTRAP,
        enabled=True,
        lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
        availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
        accepted_contract_revision_id=None,
        active_config_revision_id=None,
        admin_version=1,
        capabilities={},
        config_schema=None,
        metadata=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_registry_dispatches_only_the_selected_method() -> None:
    issued = _Verifier(
        RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        _authentication(RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN),
    )
    kubernetes = _Verifier(
        RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
        _authentication(RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT),
    )
    registry = ProviderAuthRegistry((issued, kubernetes))

    result = await registry.verify(
        method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
        secret="selected-secret",
        now=_NOW,
    )

    assert result.auth_method is RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT
    assert issued.calls == []
    assert kubernetes.calls == ["selected-secret"]


def test_registry_rejects_duplicate_methods() -> None:
    verifier = _Verifier(
        RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        _authentication(RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN),
    )

    with pytest.raises(ValueError, match="duplicate Provider auth verifier"):
        ProviderAuthRegistry((verifier, verifier))


@pytest.mark.asyncio
async def test_registry_rejects_unregistered_method_without_fallback() -> None:
    verifier = _Verifier(
        RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
        _authentication(RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN),
    )
    registry = ProviderAuthRegistry((verifier,))

    with pytest.raises(RuntimeProviderCredentialUnavailable):
        await registry.verify(
            method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            secret="wrong-method-secret",
            now=_NOW,
        )

    assert verifier.calls == []


@pytest.mark.asyncio
async def test_registry_rejects_mismatched_verifier_result_method() -> None:
    verifier = _Verifier(
        RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
        _authentication(RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN),
    )
    registry = ProviderAuthRegistry((verifier,))

    with pytest.raises(
        RuntimeProviderCredentialUnavailable,
        match="auth_method_unavailable",
    ):
        await registry.verify(
            method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            secret="service-account-token",
            now=_NOW,
        )


@pytest.mark.asyncio
async def test_kubernetes_api_reviewer_derives_expiry_after_authentication() -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    expires_at = _NOW + datetime.timedelta(minutes=10)
    api.create_token_review = AsyncMock(
        return_value=V1TokenReview(
            spec=V1TokenReviewSpec(token="reviewed-token"),
            status=V1TokenReviewStatus(
                authenticated=True,
                audiences=["azents-runtime-control"],
                user=V1UserInfo(username=_SUBJECT),
            ),
        )
    )
    reviewer = KubernetesApiTokenReviewer(api=api)

    result = await reviewer.review(
        token=_jwt(expires_at=expires_at),
        audience="azents-runtime-control",
    )

    assert result.authenticated
    assert result.username == _SUBJECT
    assert result.audiences == frozenset({"azents-runtime-control"})
    assert result.evidence_expires_at == expires_at


@pytest.mark.asyncio
async def test_kubernetes_api_reviewer_ignores_expiry_when_unauthenticated() -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    api.create_token_review = AsyncMock(
        return_value=V1TokenReview(
            spec=V1TokenReviewSpec(token="reviewed-token"),
            status=V1TokenReviewStatus(
                authenticated=False,
                audiences=[],
                user=V1UserInfo(username=""),
            ),
        )
    )
    reviewer = KubernetesApiTokenReviewer(api=api)

    result = await reviewer.review(
        token=_jwt(expires_at=_NOW + datetime.timedelta(minutes=10)),
        audience="azents-runtime-control",
    )

    assert not result.authenticated
    assert result.username is None
    assert result.evidence_expires_at is None


@pytest.mark.asyncio
async def test_kubernetes_api_reviewer_rejects_missing_status() -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    api.create_token_review = AsyncMock(
        return_value=V1TokenReview(
            spec=V1TokenReviewSpec(token="reviewed-token"),
            status=None,
        )
    )
    reviewer = KubernetesApiTokenReviewer(api=api)

    result = await reviewer.review(
        token=_jwt(expires_at=_NOW + datetime.timedelta(minutes=10)),
        audience="azents-runtime-control",
    )

    assert not result.authenticated
    assert result.username is None
    assert result.audiences == frozenset()
    assert result.evidence_expires_at is None


@pytest.mark.asyncio
async def test_kubernetes_api_reviewer_maps_api_rejection_to_auth_failure() -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    api.create_token_review = AsyncMock(side_effect=ApiException(status=403))
    reviewer = KubernetesApiTokenReviewer(api=api)

    with pytest.raises(
        RuntimeProviderCredentialUnavailable,
        match="workload_identity_unavailable",
    ):
        await reviewer.review(
            token=_jwt(expires_at=_NOW + datetime.timedelta(minutes=10)),
            audience="azents-runtime-control",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "review",
    (
        KubernetesServiceAccountTokenReview(
            authenticated=False,
            username=_SUBJECT,
            audiences=frozenset({"azents-runtime-control"}),
            evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
        ),
        KubernetesServiceAccountTokenReview(
            authenticated=True,
            username=_SUBJECT,
            audiences=frozenset({"another-audience"}),
            evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
        ),
        KubernetesServiceAccountTokenReview(
            authenticated=True,
            username="not-a-service-account",
            audiences=frozenset({"azents-runtime-control"}),
            evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
        ),
        KubernetesServiceAccountTokenReview(
            authenticated=True,
            username=_SUBJECT,
            audiences=frozenset({"azents-runtime-control"}),
            evidence_expires_at=_NOW,
        ),
        KubernetesServiceAccountTokenReview(
            authenticated=True,
            username=_SUBJECT,
            audiences=frozenset({"azents-runtime-control"}),
            evidence_expires_at=None,
        ),
    ),
)
async def test_kubernetes_verifier_rejects_invalid_workload_evidence(
    review: KubernetesServiceAccountTokenReview,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    verifier = KubernetesServiceAccountProviderAuthVerifier(
        session_manager=_session_manager(session),
        provider_repository=AsyncMock(spec=RuntimeProviderRepository),
        binding_repository=AsyncMock(spec=RuntimeProviderAuthBindingRepository),
        token_reviewer=_TokenReviewer(review),
    )

    with pytest.raises(
        RuntimeProviderCredentialUnavailable,
        match="workload_identity_unavailable",
    ):
        await verifier.verify(secret="service-account-token", now=_NOW)


@pytest.mark.asyncio
async def test_kubernetes_verifier_resolves_exact_bootstrap_binding() -> None:
    session = AsyncMock(spec=AsyncSession)
    binding_repository = AsyncMock(spec=RuntimeProviderAuthBindingRepository)
    provider_repository = AsyncMock(spec=RuntimeProviderRepository)
    binding_repository.get_active_by_subject.return_value = _kubernetes_binding()
    binding_repository.mark_authenticated.return_value = True
    provider_repository.get_by_id.return_value = _kubernetes_provider()
    verifier = KubernetesServiceAccountProviderAuthVerifier(
        session_manager=_session_manager(session),
        provider_repository=provider_repository,
        binding_repository=binding_repository,
        token_reviewer=_TokenReviewer(
            KubernetesServiceAccountTokenReview(
                authenticated=True,
                username=_SUBJECT,
                audiences=frozenset({"azents-runtime-control"}),
                evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
            )
        ),
    )

    result = await verifier.verify(secret="service-account-token", now=_NOW)

    assert result.binding_id == "binding-1"
    assert result.provider_id == "provider-row-1"
    assert result.credential_id is None
    assert result.auth_method is RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT
    binding_repository.mark_authenticated.assert_awaited_once()


@pytest.mark.asyncio
async def test_kubernetes_verifier_rejects_concurrent_binding_revocation() -> None:
    session = AsyncMock(spec=AsyncSession)
    binding_repository = AsyncMock(spec=RuntimeProviderAuthBindingRepository)
    provider_repository = AsyncMock(spec=RuntimeProviderRepository)
    binding_repository.get_active_by_subject.return_value = _kubernetes_binding()
    binding_repository.mark_authenticated.return_value = False
    provider_repository.get_by_id.return_value = _kubernetes_provider()
    verifier = KubernetesServiceAccountProviderAuthVerifier(
        session_manager=_session_manager(session),
        provider_repository=provider_repository,
        binding_repository=binding_repository,
        token_reviewer=_TokenReviewer(
            KubernetesServiceAccountTokenReview(
                authenticated=True,
                username=_SUBJECT,
                audiences=frozenset({"azents-runtime-control"}),
                evidence_expires_at=_NOW + datetime.timedelta(minutes=5),
            )
        ),
    )

    with pytest.raises(
        RuntimeProviderCredentialUnavailable,
        match="binding_unavailable",
    ):
        await verifier.verify(secret="service-account-token", now=_NOW)
