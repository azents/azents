"""Provider authentication verifier registry and method implementations."""

import base64
import binascii
import datetime
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from azcommon.datetime import tznow
from kubernetes_asyncio.client.api.authentication_v1_api import AuthenticationV1Api
from kubernetes_asyncio.client.models.v1_token_review import V1TokenReview
from kubernetes_asyncio.client.models.v1_token_review_spec import V1TokenReviewSpec
from kubernetes_asyncio.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderLifecycleState,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

from .data import (
    KubernetesServiceAccountTokenReview,
    RuntimeProviderCredentialAuthentication,
    RuntimeProviderCredentialUnavailable,
)

_TERMINAL = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)
_SERVICE_ACCOUNT_SUBJECT = re.compile(r"^system:serviceaccount:([^:]+):([^:]+)$")
_KUBERNETES_AUDIENCE = "azents-runtime-control"


class KubernetesServiceAccountTokenReviewer(Protocol):
    """Review a Kubernetes ServiceAccount token against one audience."""

    async def review(
        self,
        *,
        token: str,
        audience: str,
    ) -> KubernetesServiceAccountTokenReview:
        """Return the Kubernetes API TokenReview result."""
        ...


@dataclass(frozen=True)
class KubernetesApiTokenReviewer:
    """Call Kubernetes TokenReview and derive JWT evidence expiry."""

    api: AuthenticationV1Api

    async def review(
        self,
        *,
        token: str,
        audience: str,
    ) -> KubernetesServiceAccountTokenReview:
        """Review a token and decode expiry only after authentication succeeds."""
        try:
            result = await self.api.create_token_review(
                V1TokenReview(spec=V1TokenReviewSpec(token=token, audiences=[audience]))
            )
        except ApiException as exc:
            raise RuntimeProviderCredentialUnavailable(
                "workload_identity_unavailable"
            ) from exc
        status = getattr(result, "status", None)
        if status is None:
            return KubernetesServiceAccountTokenReview(
                authenticated=False,
                username=None,
                audiences=frozenset(),
                evidence_expires_at=None,
            )
        authenticated = bool(status.authenticated)
        username = None
        audiences = frozenset()
        if authenticated:
            user = getattr(status, "user", None)
            username = user.username if user is not None else None
            audiences = frozenset(status.audiences or ())
        evidence_expires_at = _jwt_expiry(token) if authenticated else None
        return KubernetesServiceAccountTokenReview(
            authenticated=authenticated,
            username=username,
            audiences=audiences,
            evidence_expires_at=evidence_expires_at,
        )


def _jwt_expiry(token: str) -> datetime.datetime | None:
    """Decode an unverified JWT expiry after TokenReview authentication."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        exp = payload["exp"]
        if isinstance(exp, bool) or not isinstance(exp, int | float):
            return None
        return datetime.datetime.fromtimestamp(exp, tz=datetime.UTC)
    except (
        binascii.Error,
        KeyError,
        OSError,
        OverflowError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None


class ProviderAuthVerifier(Protocol):
    """Verify one explicit Provider authentication method."""

    @property
    def method(self) -> RuntimeProviderAuthMethod:
        """Return the explicitly supported authentication method."""
        ...

    async def verify(
        self,
        *,
        secret: str,
        now: datetime.datetime,
    ) -> RuntimeProviderCredentialAuthentication:
        """Verify evidence and return normalized Provider identity."""
        ...


@dataclass(frozen=True)
class IssuedTokenProviderAuthVerifier:
    """Verify Azents-issued Provider credentials against binding state."""

    session_manager: SessionManager[AsyncSession]
    repository: RuntimeProviderControlRepository
    provider_repository: RuntimeProviderRepository
    binding_repository: RuntimeProviderAuthBindingRepository
    credential_verifier: RuntimeProviderCredentialVerifier
    method: RuntimeProviderAuthMethod = RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN

    async def verify(
        self,
        *,
        secret: str,
        now: datetime.datetime,
    ) -> RuntimeProviderCredentialAuthentication:
        """Resolve one active, unexpired issued credential and its binding."""
        async with self.session_manager() as session:
            credential = await self.repository.get_active_credential_by_verifier(
                session,
                verifier=self.credential_verifier.verifier_for(secret),
                now=now,
            )
            if credential is None or not self.credential_verifier.matches(
                secret, credential.verifier
            ):
                raise RuntimeProviderCredentialUnavailable("credential_unavailable")
            binding = await self.binding_repository.get_by_id(
                session,
                binding_id=credential.binding_id,
                for_update=False,
            )
            if (
                binding is None
                or binding.state is not RuntimeProviderBindingState.ACTIVE
                or binding.auth_method is not self.method
            ):
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
            if binding.provider_id != credential.provider_id:
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=binding.provider_id,
                for_update=False,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderCredentialUnavailable("provider_unavailable")
            if not await self.repository.mark_credential_used(
                session,
                credential_id=credential.id,
                used_at=now,
            ):
                raise RuntimeProviderCredentialUnavailable("credential_unavailable")
            evidence_expires_at = credential.expires_at
            if not await self.binding_repository.mark_authenticated(
                session,
                binding_id=binding.id,
                authenticated_at=now,
            ):
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
        return RuntimeProviderCredentialAuthentication(
            binding_id=binding.id,
            credential_id=credential.id,
            provider_id=provider.id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
            auth_method=self.method,
            auth_subject=binding.subject,
            evidence_expires_at=evidence_expires_at,
        )


@dataclass(frozen=True)
class KubernetesServiceAccountProviderAuthVerifier:
    """Verify Kubernetes workload evidence against a bootstrap-owned binding."""

    session_manager: SessionManager[AsyncSession]
    provider_repository: RuntimeProviderRepository
    binding_repository: RuntimeProviderAuthBindingRepository
    token_reviewer: KubernetesServiceAccountTokenReviewer
    method: RuntimeProviderAuthMethod = (
        RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT
    )

    async def verify(
        self,
        *,
        secret: str,
        now: datetime.datetime,
    ) -> RuntimeProviderCredentialAuthentication:
        """Verify exact ServiceAccount subject, audience, binding, and expiry."""
        review = await self.token_reviewer.review(
            token=secret,
            audience=_KUBERNETES_AUDIENCE,
        )
        if (
            not review.authenticated
            or review.username is None
            or _KUBERNETES_AUDIENCE not in review.audiences
            or review.evidence_expires_at is None
            or review.evidence_expires_at <= now
        ):
            raise RuntimeProviderCredentialUnavailable("workload_identity_unavailable")
        match = _SERVICE_ACCOUNT_SUBJECT.fullmatch(review.username)
        if match is None:
            raise RuntimeProviderCredentialUnavailable("workload_identity_unavailable")
        subject = review.username
        async with self.session_manager() as session:
            binding = await self.binding_repository.get_active_by_subject(
                session,
                auth_method=self.method,
                subject=subject,
            )
            if (
                binding is None
                or binding.owner is not RuntimeProviderBindingOwner.BOOTSTRAP
            ):
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
            config = binding.config or {}
            configured_audience = config.get("audience")
            configured_namespace = config.get("namespace")
            configured_service_account_name = config.get("service_account_name")
            if (
                configured_audience != _KUBERNETES_AUDIENCE
                or configured_namespace != match.group(1)
                or configured_service_account_name != match.group(2)
            ):
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=binding.provider_id,
                for_update=False,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderCredentialUnavailable("provider_unavailable")
            if not await self.binding_repository.mark_authenticated(
                session,
                binding_id=binding.id,
                authenticated_at=now,
            ):
                raise RuntimeProviderCredentialUnavailable("binding_unavailable")
        return RuntimeProviderCredentialAuthentication(
            binding_id=binding.id,
            credential_id=None,
            provider_id=provider.id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
            auth_method=self.method,
            auth_subject=subject,
            evidence_expires_at=review.evidence_expires_at,
        )


@dataclass(frozen=True)
class ProviderAuthRegistry:
    """Dispatch Provider evidence to exactly one registered verifier."""

    verifiers: Sequence[ProviderAuthVerifier]
    _by_method: Mapping[RuntimeProviderAuthMethod, ProviderAuthVerifier] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Reject duplicate or mislabelled verifier registrations."""
        by_method: dict[RuntimeProviderAuthMethod, ProviderAuthVerifier] = {}
        for verifier in self.verifiers:
            if verifier.method in by_method:
                raise ValueError(f"duplicate Provider auth verifier: {verifier.method}")
            by_method[verifier.method] = verifier
        object.__setattr__(self, "_by_method", by_method)

    async def verify(
        self,
        *,
        method: RuntimeProviderAuthMethod,
        secret: str,
        now: datetime.datetime | None = None,
    ) -> RuntimeProviderCredentialAuthentication:
        """Verify evidence using the explicitly selected method only."""
        verifier = self._by_method.get(method)
        if verifier is None or verifier.method is not method:
            raise RuntimeProviderCredentialUnavailable("auth_method_unavailable")
        authentication = await verifier.verify(secret=secret, now=now or tznow())
        if authentication.auth_method is not method:
            raise RuntimeProviderCredentialUnavailable("auth_method_unavailable")
        return authentication
