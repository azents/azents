"""Actual Credential projections after genuine PostgreSQL reads have closed."""

import asyncio
import dataclasses
from unittest.mock import Mock, create_autospec

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from types_aiobotocore_ses.client import SESClient

import azents.api.public.auth.v1 as auth_api
import azents.api.public.security.v1 as security_api
from azents.api.public.auth.v1.data import LoginMethodsResponse
from azents.api.public.security.v1.data import GetAuthMethodsResponse
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.config import (
    AuthConfig,
    EmailConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.credential_read import CredentialReadFact, CredentialReadKind
from azents.core.email.deps import create_template_environment
from azents.core.email.service import EmailService
from azents.rdb.session import SessionManager
from azents.repos.auth_operation import AuthOperationRepository
from azents.repos.credential_read_operations import CredentialReadOperationRepository
from azents.repos.credential_read_operations_test import (
    CredentialReadFixture,
    CredentialReadScope,
    credential_read_fixture,
    credential_rows,
    seed_credential_subject,
)
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)
from azents.repos.security_operation import SecurityOperationRepository
from azents.services.auth import AuthService
from azents.services.credential.data import (
    CredentialRemoveCheck,
    CredentialSummary,
    CredentialType,
    CredentialUnavailableReason,
    LoginCredentialProjection,
)
from azents.services.credential.providers import (
    CredentialProvider,
    EmailCredentialProvider,
    PasswordCredentialProvider,
)
from azents.services.credential.service import CredentialService
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
)
from azents.services.security import SecurityService


class ClosedEmailService(EmailService):
    """Observe the actual pure configured property; client is never contacted."""

    def __init__(self, scope: CredentialReadScope, configured: bool) -> None:
        config = (
            EmailConfig(
                sender="synthetic@example.test",
                sender_name="Synthetic",
                ses_region="us-west-2",
                ses_endpoint=None,
                verification_expire_minutes=10,
                web_url="https://example.test",
            )
            if configured
            else None
        )
        client = create_autospec(SESClient, instance=True) if configured else None
        super().__init__(
            config=config,
            ses_client=client,
            template_environment=create_template_environment(),
        )
        self.client_probe: Mock | None = client
        self.scope = scope
        self.availability_reads = 0

    @property
    def configured(self) -> bool:
        self.scope.assert_closed()
        self.availability_reads += 1
        return super().configured


class ClosedPasswordProvider(PasswordCredentialProvider):
    def __init__(
        self, scope: CredentialReadScope, calls: list[str], label: str
    ) -> None:
        super().__init__()
        self.scope = scope
        self.calls = calls
        self.label = label

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        self.calls.append(self.label)
        return await super().get_user_summary(fact=fact)

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        self.calls.append(self.label)
        return await super().get_login_summary(fact=fact)


class ClosedEmailProvider(EmailCredentialProvider):
    def __init__(self, email_service: ClosedEmailService, calls: list[str]) -> None:
        super().__init__(email_service=email_service)
        self.scope = email_service.scope
        self.calls = calls

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        self.calls.append("email")
        return await super().get_user_summary(fact=fact)

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        self.calls.append("email")
        return await super().get_login_summary(fact=fact)


class ClosedCredentialService(CredentialService):
    def __init__(
        self,
        repository: CredentialReadOperationRepository,
        providers: list[CredentialProvider],
        scope: CredentialReadScope,
    ) -> None:
        super().__init__(repository=repository, providers=providers)
        self.scope = scope
        self.projection_calls: list[str] = []

    def _apply_remove_invariants(
        self, summaries: list[CredentialSummary]
    ) -> list[CredentialSummary]:
        self.scope.assert_closed()
        self.projection_calls.append("remove_invariants")
        return super()._apply_remove_invariants(summaries)

    def _email_flow_available(self) -> bool:
        self.scope.assert_closed()
        self.projection_calls.append("public_availability")
        return super()._email_flow_available()


@dataclasses.dataclass(frozen=True)
class BoundaryFixture:
    reads: CredentialReadFixture
    service: ClosedCredentialService
    email: ClosedEmailService
    calls: list[str]


def boundary_fixture(
    reads: CredentialReadFixture, *, smtp: bool, order: tuple[str, ...]
) -> BoundaryFixture:
    calls: list[str] = []
    email = ClosedEmailService(reads.scope, smtp)
    providers: list[CredentialProvider] = []
    for item in order:
        if item == "email":
            providers.append(ClosedEmailProvider(email, calls))
        else:
            assert item == "password"
            providers.append(ClosedPasswordProvider(reads.scope, calls, item))
    service = ClosedCredentialService(reads.repository, providers, reads.scope)
    return BoundaryFixture(reads, service, email, calls)


@pytest.fixture
async def boundary_reads(
    rdb_session_manager: SessionManager[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> CredentialReadFixture:
    return credential_read_fixture(rdb_session_manager, monkeypatch)


@pytest.mark.parametrize("smtp", [False, True])
@pytest.mark.parametrize(
    "method",
    ["user", "login", "security", "elevation", "remove_password", "remove_email"],
)
async def test_actual_provider_config_and_projection_after_real_db_completion(
    boundary_reads: CredentialReadFixture,
    smtp: bool,
    method: str,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=False,
        secondary_verified=True,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=smtp, order=("password", "email"))
    before = await credential_rows(reads, subject.user_id)
    if method == "user":
        summaries = await boundary.service.get_user_credentials(user_id=subject.user_id)
        assert summaries is not None
        password, email = summaries
        assert password.valid and password.can_login and password.can_elevate
        assert password.can_remove is smtp
        assert password.unavailable_reason is (
            None if smtp else CredentialUnavailableReason.LAST_VALID_CREDENTIAL
        )
        assert email.configured and email.valid is smtp and email.can_remove
        assert email.unavailable_reason is (
            None if smtp else CredentialUnavailableReason.SMTP_NOT_CONFIGURED
        )
    elif method == "login":
        projection = await boundary.service.get_login_projection(
            email=subject.primary_email
        )
        assert projection.model_dump() == {
            "has_password": True,
            "email_available": smtp,
        }
        assert boundary.email.availability_reads == 1, (
            "Public availability ignores exact unverified address fact"
        )
    elif method in {"security", "elevation"}:
        projections = await (
            boundary.service.get_security_projection(user_id=subject.user_id)
            if method == "security"
            else boundary.service.get_elevation_projection(user_id=subject.user_id)
        )
        assert projections is not None
        assert [p.type for p in projections] == [
            CredentialType.PASSWORD,
            CredentialType.EMAIL,
        ]
        assert [p.enabled for p in projections] == [True, smtp]
        assert all(
            p.enabled == (p.valid if method == "security" else p.can_elevate)
            for p in projections
        )
        assert projections[1].can_remove and projections[1].configured
        assert projections[1].unavailable_reason is (
            None if smtp else CredentialUnavailableReason.SMTP_NOT_CONFIGURED
        )
    else:
        target = (
            CredentialType.PASSWORD
            if method == "remove_password"
            else CredentialType.EMAIL
        )
        result = await boundary.service.check_remove_allowed(
            user_id=subject.user_id, credential_type=target
        )
        allowed = smtp or target is CredentialType.EMAIL
        assert result == CredentialRemoveCheck(
            allowed=allowed,
            reason=None
            if allowed
            else CredentialUnavailableReason.LAST_VALID_CREDENTIAL,
        )
    assert boundary.calls == ["password", "email"]
    reads.scope.assert_closed()
    assert reads.scope.commits == 1
    assert await credential_rows(reads, subject.user_id) == before
    if boundary.email.client_probe is not None:
        assert boundary.email.client_probe.mock_calls == []


@pytest.mark.parametrize("method", ["user", "security", "elevation", "remove"])
async def test_missing_user_closes_real_scope_skips_all_provider_and_config_work(
    boundary_reads: CredentialReadFixture,
    method: str,
) -> None:
    boundary = boundary_fixture(boundary_reads, smtp=True, order=("password", "email"))
    if method == "user":
        result = await boundary.service.get_user_credentials(user_id="0" * 32)
    elif method == "security":
        result = await boundary.service.get_security_projection(user_id="0" * 32)
    elif method == "elevation":
        result = await boundary.service.get_elevation_projection(user_id="0" * 32)
    else:
        result = await boundary.service.check_remove_allowed(
            user_id="0" * 32, credential_type=CredentialType.PASSWORD
        )
    assert result is None
    assert boundary.calls == [] and boundary.email.availability_reads == 0
    assert boundary.service.projection_calls == []
    assert boundary_reads.fault.stages() == ["user_get"]
    boundary_reads.scope.assert_closed()


@pytest.mark.parametrize("method", ["user", "login", "security", "elevation", "remove"])
async def test_empty_providers_still_complete_original_read_before_empty_projection(
    boundary_reads: CredentialReadFixture,
    method: str,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=False,
        secondary_verified=True,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=True, order=())
    if method == "user":
        assert (
            await boundary.service.get_user_credentials(user_id=subject.user_id) == []
        )
    elif method == "login":
        assert await boundary.service.get_login_projection(
            email=subject.primary_email
        ) == LoginCredentialProjection(has_password=False, email_available=False)
    elif method == "security":
        assert (
            await boundary.service.get_security_projection(user_id=subject.user_id)
            == []
        )
    elif method == "elevation":
        assert (
            await boundary.service.get_elevation_projection(user_id=subject.user_id)
            == []
        )
    else:
        assert await boundary.service.check_remove_allowed(
            user_id=subject.user_id, credential_type=CredentialType.PASSWORD
        ) == CredentialRemoveCheck(
            allowed=False, reason=CredentialUnavailableReason.NOT_CONFIGURED
        )
    assert boundary.calls == [] and boundary.email.availability_reads == 0
    assert reads.fault.stages() == ([] if method == "login" else ["user_get"])
    assert len(reads.scope.sessions) == 1 and reads.scope.commits == 1
    reads.scope.assert_closed()


async def test_duplicate_real_password_queries_count_duplicate_valid_summaries(
    boundary_reads: CredentialReadFixture,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=False,
        secondary_verified=False,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=False, order=("password", "password"))
    summaries = await boundary.service.get_user_credentials(user_id=subject.user_id)
    assert summaries is not None and len(summaries) == 2
    assert all(
        summary.can_remove and summary.unavailable_reason is None
        for summary in summaries
    )
    assert reads.fault.stages() == ["user_get", "password_exists", "password_exists"]
    assert boundary.calls == ["password", "password"]
    reads.scope.assert_closed()


class SummaryPassword(ClosedPasswordProvider):
    """Pure aggregation test variant; real repository facts are not faked."""

    def __init__(
        self,
        scope: CredentialReadScope,
        calls: list[str],
        label: str,
        summary: CredentialSummary,
    ) -> None:
        super().__init__(scope, calls, label)
        self.summary = summary

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        assert fact.kind is CredentialReadKind.PASSWORD and fact.configured
        self.calls.append(self.label)
        return self.summary

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        return await self.get_user_summary(fact=fact)


async def test_last_password_public_first_target_removal_and_recovery_reason(
    boundary_reads: CredentialReadFixture,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=False,
        secondary_verified=False,
        disabled=False,
    )
    calls: list[str] = []
    first = CredentialSummary(
        type=CredentialType.PASSWORD,
        configured=True,
        valid=True,
        can_login=True,
        can_elevate=True,
        can_remove=True,
        unavailable_reason=None,
    )
    last = CredentialSummary(
        type=CredentialType.PASSWORD,
        configured=True,
        valid=False,
        can_login=False,
        can_elevate=False,
        can_remove=False,
        unavailable_reason=CredentialUnavailableReason.RECOVERY_REQUIRED,
    )
    service = ClosedCredentialService(
        reads.repository,
        [
            SummaryPassword(reads.scope, calls, "first", first),
            SummaryPassword(reads.scope, calls, "last", last),
        ],
        reads.scope,
    )
    projection = await service.get_login_projection(email=subject.primary_email)
    assert projection == LoginCredentialProjection(
        has_password=False, email_available=False
    )
    target = await service.check_remove_allowed(
        user_id=subject.user_id, credential_type=CredentialType.PASSWORD
    )
    assert target == CredentialRemoveCheck(
        allowed=False, reason=CredentialUnavailableReason.LAST_VALID_CREDENTIAL
    )
    summaries = await service.get_user_credentials(user_id=subject.user_id)
    assert summaries is not None and summaries[1].can_remove
    assert (
        summaries[1].unavailable_reason is CredentialUnavailableReason.RECOVERY_REQUIRED
    )
    assert calls == ["first", "last"] * 3
    reads.scope.assert_closed()


class EmailClaimProvider:
    """A structural provider double is not an actual EmailCredentialProvider."""

    credential_type = CredentialType.EMAIL
    read_kind = CredentialReadKind.EMAIL

    def __init__(self, scope: CredentialReadScope) -> None:
        self.scope = scope

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        return CredentialSummary(
            type=CredentialType.EMAIL,
            configured=fact.configured,
            valid=fact.configured,
            can_login=fact.configured,
            can_elevate=fact.configured,
            can_remove=False,
            unavailable_reason=None,
        )

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        return await self.get_user_summary(fact=fact)


async def test_public_email_availability_requires_actual_email_provider_subtype(
    boundary_reads: CredentialReadFixture,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=False,
        primary_verified=True,
        secondary_verified=False,
        disabled=False,
    )
    service = ClosedCredentialService(
        reads.repository, [EmailClaimProvider(reads.scope)], reads.scope
    )
    assert await service.get_login_projection(
        email=subject.primary_email
    ) == LoginCredentialProjection(has_password=False, email_available=False)
    reads.scope.assert_closed()
    # The ordinary boundary provider is an actual subtype and exposes configured
    # delivery even for an unknown address, without inventing a new provider kind.
    boundary = boundary_fixture(reads, smtp=True, order=("email",))
    assert await boundary.service.get_login_projection(
        email="unknown@example.test"
    ) == LoginCredentialProjection(has_password=False, email_available=True)
    reads.scope.assert_closed()


@pytest.mark.parametrize("flow", ["user", "login"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_service_query_error_cancel_transparent_and_no_application_projection(
    boundary_reads: CredentialReadFixture,
    flow: str,
    cancel: bool,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=True,
        secondary_verified=False,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=True, order=("password", "email"))
    reads.fault.stage = "password_exists"
    reads.fault.pause = cancel
    if not cancel:
        reads.fault.error = RuntimeError("actual read failed")

    async def action() -> None:
        if flow == "user":
            await boundary.service.get_user_credentials(user_id=subject.user_id)
        else:
            await boundary.service.get_login_projection(email=subject.primary_email)

    task = asyncio.create_task(action())
    try:
        if cancel:
            await asyncio.wait_for(reads.fault.reached.wait(), timeout=10)
            task.cancel("after actual selected credential SQL")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert boundary.calls == [] and boundary.email.availability_reads == 0
        assert boundary.service.projection_calls == []
        assert reads.scope.commits == 0 and reads.scope.failures == 1
        reads.scope.assert_closed()
    finally:
        reads.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class FailingSummaryPassword(ClosedPasswordProvider):
    def __init__(
        self, scope: CredentialReadScope, calls: list[str], *, cancel: bool
    ) -> None:
        super().__init__(scope, calls, "failing_password")
        self.cancel = cancel
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        self.scope.assert_closed()
        assert fact.kind is CredentialReadKind.PASSWORD
        self.calls.append(self.label)
        self.reached.set()
        if self.cancel:
            await self.release.wait()
        raise RuntimeError("pure projection failed after closed read")

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        return await self.get_user_summary(fact=fact)


@pytest.mark.parametrize("flow", ["user", "login"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_application_error_cancel_after_completed_read_does_not_reopen_sql(
    boundary_reads: CredentialReadFixture,
    flow: str,
    cancel: bool,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=True,
        secondary_verified=False,
        disabled=False,
    )
    calls: list[str] = []
    provider = FailingSummaryPassword(reads.scope, calls, cancel=cancel)
    service = ClosedCredentialService(reads.repository, [provider], reads.scope)
    before = await credential_rows(reads, subject.user_id)

    async def action() -> None:
        if flow == "user":
            await service.get_user_credentials(user_id=subject.user_id)
        else:
            await service.get_login_projection(email=subject.primary_email)

    task = asyncio.create_task(action())
    try:
        if cancel:
            await asyncio.wait_for(provider.reached.wait(), timeout=10)
            task.cancel("after actual repository closed before pure projection")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert calls == ["failing_password"]
        assert reads.scope.commits == 1 and reads.scope.failures == 0
        reads.scope.assert_closed()
        assert await credential_rows(reads, subject.user_id) == before
    finally:
        provider.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def auth_config() -> AuthConfig:
    return AuthConfig(
        jwt=JWTConfig(secret_key="synthetic-only"),
        refresh_token=RefreshTokenConfig(),
        signup_token=SignupTokenConfig(),
    )


def actual_auth_service(
    boundary: BoundaryFixture, *, unused: list[Mock]
) -> AuthService:
    """Unused write dependencies are autospecs, never genuine SQL proof."""
    verification = create_autospec(EmailVerificationOperationRepository, instance=True)
    operations = create_autospec(AuthOperationRepository, instance=True)
    unused.extend([verification, operations])
    return AuthService(
        email_service=boundary.email,
        email_verification_operation_repository=verification,
        auth_operation_repository=operations,
        credential_service=boundary.service,
        terminal_invalidation_publisher=NoopRuntimeTerminalInvalidationPublisher(),
        auth_config=auth_config(),
        email_config=boundary.email.config,
    )


def actual_security_service(
    boundary: BoundaryFixture, *, unused: list[Mock]
) -> SecurityService:
    verification = create_autospec(EmailVerificationOperationRepository, instance=True)
    operations = create_autospec(SecurityOperationRepository, instance=True)
    unused.extend([verification, operations])
    return SecurityService(
        email_service=boundary.email,
        email_verification_operation_repository=verification,
        operation_repository=operations,
        credential_service=boundary.service,
        auth_config=auth_config(),
        email_config=boundary.email.config,
    )


@pytest.mark.parametrize(
    "method", ["public_login", "auth_methods", "elevation_methods"]
)
@pytest.mark.parametrize("smtp", [False, True])
async def test_actual_auth_security_and_public_output_conversion_after_closed_pg(
    boundary_reads: CredentialReadFixture,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    smtp: bool,
) -> None:
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=False,
        secondary_verified=True,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=smtp, order=("password", "email"))
    converted: list[str] = []

    class ClosedLoginResponse(LoginMethodsResponse):
        def model_post_init(self, context: object) -> None:
            reads.scope.assert_closed()
            converted.append("public_login")
            super().model_post_init(context)

    class ClosedSecurityResponse(GetAuthMethodsResponse):
        def model_post_init(self, context: object) -> None:
            reads.scope.assert_closed()
            converted.append(method)
            super().model_post_init(context)

    monkeypatch.setattr(auth_api, "LoginMethodsResponse", ClosedLoginResponse)
    monkeypatch.setattr(security_api, "GetAuthMethodsResponse", ClosedSecurityResponse)
    unused: list[Mock] = []
    if method == "public_login":
        service = actual_auth_service(boundary, unused=unused)
        result = await auth_api.get_login_methods(
            service, email=subject.secondary_email
        )
        assert result.model_dump() == {"has_password": True, "email_available": smtp}
    else:
        service = actual_security_service(boundary, unused=unused)
        current = CurrentUser(
            user_id=subject.user_id, session_id="synthetic-session", elevated=True
        )
        result = await (
            security_api.get_auth_methods(service, current)
            if method == "auth_methods"
            else security_api.get_elevation_methods(service, current)
        )
        assert len(result.methods) == 2
        password, email = result.methods
        assert password.type == "password" and email.type == "email"
        assert password.enabled and email.enabled is smtp
        assert email.configured and email.can_remove
        assert email.unavailable_reason == (None if smtp else "smtp_not_configured")
        assert password.unavailable_reason == (
            None if smtp else "last_valid_credential"
        )
    assert all(mock.mock_calls == [] for mock in unused)
    assert converted == [method]
    reads.scope.assert_closed()


@pytest.mark.parametrize(
    "case,path,expected",
    [
        ("unauthenticated", "/auth-methods", 401),
        ("not_elevated", "/auth-methods", 403),
        ("missing_projection", "/auth-methods", 404),
        ("missing_projection", "/elevation-methods", 404),
        ("not_elevated", "/elevation-methods", 200),
    ],
)
async def test_actual_security_route_harness_keeps_stub_admission_and_projection_order(
    boundary_reads: CredentialReadFixture,
    case: str,
    path: str,
    expected: int,
) -> None:
    """Actual route/elevation guard, explicit existing-user admission stub only."""
    reads = boundary_reads
    subject = await seed_credential_subject(
        reads.manager,
        password=True,
        primary_verified=True,
        secondary_verified=False,
        disabled=False,
    )
    boundary = boundary_fixture(reads, smtp=True, order=("password", "email"))
    unused: list[Mock] = []
    service = actual_security_service(boundary, unused=unused)
    app = FastAPI()
    app.include_router(security_api.router, prefix="/security/v1")

    async def current_user_stub() -> CurrentUser:
        if case == "unauthenticated":
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return CurrentUser(
            user_id="0" * 32 if case == "missing_projection" else subject.user_id,
            session_id="synthetic-session",
            elevated=case != "not_elevated",
        )

    def security_service() -> SecurityService:
        return service

    app.dependency_overrides[get_current_user] = current_user_stub
    app.dependency_overrides[SecurityService] = security_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/security/v1{path}")
    assert response.status_code == expected
    if expected == 401:
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Not authenticated"}
    elif expected == 403:
        assert response.json() == {"detail": "Elevated access required"}
    elif expected == 404:
        assert response.json() == {"detail": "User not found."}
    else:
        assert len(response.json()["methods"]) == 2
    if expected in {401, 403}:
        assert reads.scope.sessions == [] and boundary.calls == []
    elif expected == 404:
        assert reads.fault.stages() == ["user_get"] and boundary.calls == []
    reads.scope.assert_closed()
    assert all(mock.mock_calls == [] for mock in unused)
