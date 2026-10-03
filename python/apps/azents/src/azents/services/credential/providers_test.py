"""Pure Credential projection and completed-operation contract regressions."""

import asyncio
import dataclasses
import inspect
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from fastapi.params import Depends

from azents.core.credential_read import (
    CredentialReadFact,
    CredentialReadKind,
    CredentialReadSnapshot,
)
from azents.rdb.deps import get_session_manager
from azents.repos.credential_read_operations import CredentialReadOperationRepository
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository
from azents.services.credential.data import (
    CredentialSummary,
    CredentialType,
    CredentialUnavailableReason,
)
from azents.services.credential.providers import (
    CredentialProvider,
    EmailCredentialProvider,
    PasswordCredentialProvider,
    get_credential_providers,
)
from azents.services.credential.service import CredentialService
from azents.services.credential.service_test import _make_email_service


class SnapshotRepository(CredentialReadOperationRepository):
    """Model completed results only; never construct or simulate SQL collaborators."""

    def __init__(
        self,
        *,
        user_snapshot: CredentialReadSnapshot | None,
        login_snapshot: CredentialReadSnapshot,
        failure: BaseException | None,
    ) -> None:
        self.user_snapshot = user_snapshot
        self.login_snapshot = login_snapshot
        self.failure = failure
        self.user_reads: list[tuple[str, tuple[CredentialReadKind, ...]]] = []
        self.login_reads: list[tuple[str, tuple[CredentialReadKind, ...]]] = []

    async def read_user_snapshot(
        self, *, user_id: str, kinds: tuple[CredentialReadKind, ...]
    ) -> CredentialReadSnapshot | None:
        """Return an already completed snapshot, without a Session or DB claim."""
        self.user_reads.append((user_id, kinds))
        if self.failure is not None:
            raise self.failure
        return self.user_snapshot

    async def read_login_snapshot(
        self, *, email: str, kinds: tuple[CredentialReadKind, ...]
    ) -> CredentialReadSnapshot:
        """Record application input and return only the completed result contract."""
        self.login_reads.append((email, kinds))
        if self.failure is not None:
            raise self.failure
        return self.login_snapshot


@dataclasses.dataclass
class FixedProjectionProvider:
    """Retain pure provider extensibility without accepting any database handle."""

    kind: CredentialReadKind
    credential_type: CredentialType
    user_summary: CredentialSummary
    login_summary: CredentialSummary
    observed_facts: list[CredentialReadFact]
    failure: BaseException | None

    @property
    def read_kind(self) -> CredentialReadKind:
        """Request one of the closed database query kinds."""
        return self.kind

    async def get_user_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        """Project a completed fact with the provider's existing summary semantics."""
        self.observed_facts.append(fact)
        if self.failure is not None:
            raise self.failure
        return self.user_summary

    async def get_login_summary(self, *, fact: CredentialReadFact) -> CredentialSummary:
        """Project the same closed fact contract for login availability."""
        self.observed_facts.append(fact)
        if self.failure is not None:
            raise self.failure
        return self.login_summary


def _summary(
    *,
    credential_type: CredentialType,
    configured: bool,
    valid: bool,
    can_elevate: bool,
    reason: CredentialUnavailableReason | None,
) -> CredentialSummary:
    """Provide explicit summary values, including deliberately raw removability."""
    return CredentialSummary(
        type=credential_type,
        configured=configured,
        valid=valid,
        can_login=valid,
        can_elevate=can_elevate,
        can_remove=False,
        unavailable_reason=reason,
    )


def _fixed_provider(
    summary: CredentialSummary, *, failure: BaseException | None
) -> FixedProjectionProvider:
    """Build a pure Protocol implementation, not a built-in Email subtype."""
    return FixedProjectionProvider(
        kind=CredentialReadKind.PASSWORD,
        credential_type=summary.type,
        user_summary=summary,
        login_summary=summary,
        observed_facts=[],
        failure=failure,
    )


def _service(
    *,
    providers: list[CredentialProvider],
    facts: tuple[CredentialReadFact, ...],
    user_present: bool,
    failure: BaseException | None,
) -> CredentialService:
    """Compose pure tests from a typed completed-operation double only."""
    snapshot = CredentialReadSnapshot(facts=facts)
    return CredentialService(
        repository=SnapshotRepository(
            user_snapshot=snapshot if user_present else None,
            login_snapshot=snapshot,
            failure=failure,
        ),
        providers=providers,
    )


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("login", [False, True])
async def test_password_provider_exact_summary(
    *, configured: bool, login: bool
) -> None:
    """Both entrypoints retain every password projection flag and nullable reason."""
    provider = PasswordCredentialProvider()
    fact = CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=configured)
    result = (
        await provider.get_login_summary(fact=fact)
        if login
        else await provider.get_user_summary(fact=fact)
    )
    assert result == CredentialSummary(
        type=CredentialType.PASSWORD,
        configured=configured,
        valid=configured,
        can_login=configured,
        can_elevate=configured,
        can_remove=configured,
        unavailable_reason=(
            None if configured else CredentialUnavailableReason.NOT_CONFIGURED
        ),
    )


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("smtp", [False, True])
@pytest.mark.parametrize("login", [False, True])
async def test_email_provider_exact_summary(
    *, configured: bool, smtp: bool, login: bool
) -> None:
    """Email verification and actual delivery presence retain distinct projections."""
    provider = EmailCredentialProvider(
        email_service=_make_email_service(configured=smtp)
    )
    fact = CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=configured)
    result = (
        await provider.get_login_summary(fact=fact)
        if login
        else await provider.get_user_summary(fact=fact)
    )
    assert result == CredentialSummary(
        type=CredentialType.EMAIL,
        configured=configured,
        valid=configured and smtp,
        can_login=configured and smtp,
        can_elevate=configured and smtp,
        can_remove=False,
        unavailable_reason=(
            CredentialUnavailableReason.NOT_CONFIGURED
            if not configured
            else None
            if smtp
            else CredentialUnavailableReason.SMTP_NOT_CONFIGURED
        ),
    )


async def test_query_kind_and_summary_types_ignore_projection_attribute_override() -> (
    None
):
    """Original mutable credential_type cannot change built-in query or summary type."""
    password = PasswordCredentialProvider(credential_type=CredentialType.EMAIL)
    email = EmailCredentialProvider(
        email_service=_make_email_service(configured=True),
        credential_type=CredentialType.PASSWORD,
    )
    assert password.read_kind is CredentialReadKind.PASSWORD
    assert email.read_kind is CredentialReadKind.EMAIL
    assert (
        await password.get_user_summary(
            fact=CredentialReadFact(kind=password.read_kind, configured=True)
        )
    ).type is CredentialType.PASSWORD
    assert (
        await email.get_login_summary(
            fact=CredentialReadFact(kind=email.read_kind, configured=True)
        )
    ).type is CredentialType.EMAIL


def test_required_frozen_facts_repository_and_canonical_dependencies() -> None:
    """Expose defining classes and required DI fields without creating DB sessions."""
    assert CredentialReadFact.__module__ == "azents.core.credential_read"
    assert CredentialReadSnapshot.__module__ == "azents.core.credential_read"
    assert [field.name for field in dataclasses.fields(CredentialReadFact)] == [
        "kind",
        "configured",
    ]
    assert [field.name for field in dataclasses.fields(CredentialReadSnapshot)] == [
        "facts"
    ]
    assert CredentialReadFact.__dataclass_params__.frozen
    assert CredentialReadSnapshot.__dataclass_params__.frozen
    assert CredentialReadOperationRepository.__dataclass_params__.frozen
    for defining_class in (
        CredentialReadFact,
        CredentialReadSnapshot,
        CredentialReadOperationRepository,
        CredentialService,
    ):
        assert all(
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
            for field in dataclasses.fields(defining_class)
        )
    assert list(inspect.signature(CredentialService).parameters) == [
        "repository",
        "providers",
    ]
    expected = {
        "session_manager": get_session_manager,
        "user_repository": UserRepository,
        "user_email_repository": UserEmailRepository,
        "password_login_repository": PasswordLoginRepository,
    }
    hints = get_type_hints(CredentialReadOperationRepository, include_extras=True)
    assert list(hints) == list(expected)
    for name, dependency in expected.items():
        assert get_origin(hints[name]) is Annotated
        metadata = get_args(hints[name])[1]
        assert isinstance(metadata, Depends)
        assert metadata.dependency is dependency
    for provider in (
        PasswordCredentialProvider,
        EmailCredentialProvider,
        CredentialProvider,
    ):
        for method in (provider.get_user_summary, provider.get_login_summary):
            assert list(inspect.signature(method).parameters) == ["self", "fact"]
            assert inspect.signature(method).parameters["fact"].default is (
                inspect.Parameter.empty
            )


def test_registration_uses_original_provider_order_and_actual_email_service() -> None:
    """No duplicate provider definition or hidden query constructor is introduced."""
    email_service = _make_email_service(configured=True)
    providers = get_credential_providers(email_service=email_service)
    assert len(providers) == 2
    assert isinstance(providers[0], PasswordCredentialProvider)
    assert isinstance(providers[1], EmailCredentialProvider)
    assert providers[1].email_service is email_service
    assert [provider.read_kind for provider in providers] == [
        CredentialReadKind.PASSWORD,
        CredentialReadKind.EMAIL,
    ]


async def test_order_duplicates_and_raw_removability_are_preserved() -> None:
    """Reversed duplicate facts do not collapse or retain raw Email can_remove=False."""
    email = EmailCredentialProvider(email_service=_make_email_service(configured=True))
    password = PasswordCredentialProvider()
    facts = (
        CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=True),
        CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),
        CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=True),
    )
    service = _service(
        providers=[email, password, email],
        facts=facts,
        user_present=True,
        failure=None,
    )
    result = await service.get_user_credentials(user_id="user-id")
    assert result is not None
    assert [summary.type for summary in result] == [
        CredentialType.EMAIL,
        CredentialType.PASSWORD,
        CredentialType.EMAIL,
    ]
    assert all(summary.can_remove for summary in result)
    assert all(summary.unavailable_reason is None for summary in result)
    assert isinstance(service.repository, SnapshotRepository)
    assert service.repository.user_reads == [
        ("user-id", tuple(fact.kind for fact in facts))
    ]


async def test_duplicate_valid_summaries_count_separately() -> None:
    """Two Password instances retain the original duplicate-based valid count."""
    service = _service(
        providers=[PasswordCredentialProvider(), PasswordCredentialProvider()],
        facts=(
            CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),
            CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),
        ),
        user_present=True,
        failure=None,
    )
    result = await service.get_user_credentials(user_id="user-id")
    assert result is not None and len(result) == 2
    assert all(summary.can_remove for summary in result)


async def test_smtp_invalid_email_removable_password_last_valid() -> None:
    """The service overrides raw removal flags without losing SMTP reason."""
    service = _service(
        providers=[
            PasswordCredentialProvider(),
            EmailCredentialProvider(
                email_service=_make_email_service(configured=False)
            ),
        ],
        facts=(
            CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),
            CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=True),
        ),
        user_present=True,
        failure=None,
    )
    result = await service.get_user_credentials(user_id="user-id")
    assert result is not None
    assert not result[0].can_remove
    assert result[0].unavailable_reason is (
        CredentialUnavailableReason.LAST_VALID_CREDENTIAL
    )
    assert result[1].configured and not result[1].valid and result[1].can_remove
    assert result[1].unavailable_reason is (
        CredentialUnavailableReason.SMTP_NOT_CONFIGURED
    )


@pytest.mark.parametrize("login", [False, True])
async def test_last_password_login_but_first_matching_removal_target(
    *, login: bool
) -> None:
    """Opposite first/last rules remain distinct for repeated Password summaries."""
    service = _service(
        providers=[PasswordCredentialProvider(), PasswordCredentialProvider()],
        facts=(
            CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),
            CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=False),
        ),
        user_present=True,
        failure=None,
    )
    if login:
        projection = await service.get_login_projection(email="submitted@example.com")
        assert not projection.has_password
    else:
        check = await service.check_remove_allowed(
            user_id="user-id", credential_type=CredentialType.PASSWORD
        )
        assert check is not None and not check.allowed
        assert check.reason is CredentialUnavailableReason.LAST_VALID_CREDENTIAL


async def test_security_elevation_enabled_distinct_and_recovery_retained() -> None:
    """A pure provider can vary elevate/valid flags without changing query identity."""
    raw = _summary(
        credential_type=CredentialType.PASSWORD,
        configured=True,
        valid=False,
        can_elevate=True,
        reason=CredentialUnavailableReason.RECOVERY_REQUIRED,
    )
    provider = _fixed_provider(raw, failure=None)
    fact = CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=False)
    service = _service(
        providers=[provider], facts=(fact,), user_present=True, failure=None
    )
    security = await service.get_security_projection(user_id="user-id")
    elevation = await service.get_elevation_projection(user_id="user-id")
    assert security is not None and elevation is not None
    assert not security[0].enabled
    assert elevation[0].enabled
    assert security[0].can_remove and elevation[0].can_remove
    assert security[0].unavailable_reason is (
        CredentialUnavailableReason.RECOVERY_REQUIRED
    )
    assert provider.observed_facts == [fact, fact]
    assert not raw.can_remove
    assert raw.unavailable_reason is CredentialUnavailableReason.RECOVERY_REQUIRED


async def test_email_availability_requires_actual_builtin_or_subtype() -> None:
    """An Email Protocol summary does not impersonate the original isinstance test."""
    raw = _summary(
        credential_type=CredentialType.EMAIL,
        configured=True,
        valid=True,
        can_elevate=True,
        reason=None,
    )
    custom = _fixed_provider(raw, failure=None)
    custom_service = _service(
        providers=[custom],
        facts=(CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),),
        user_present=True,
        failure=None,
    )
    assert not (
        await custom_service.get_login_projection(email="unknown@example.com")
    ).email_available

    class EmailSubtype(EmailCredentialProvider):
        """Use the real inherited read_kind and local availability behavior."""

    subtype = EmailSubtype(email_service=_make_email_service(configured=True))
    subtype_service = _service(
        providers=[subtype],
        facts=(CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=False),),
        user_present=True,
        failure=None,
    )
    result = await subtype_service.get_login_projection(email="unknown@example.com")
    assert not result.has_password
    assert result.email_available


@pytest.mark.parametrize("user_present", [False, True])
async def test_empty_providers_still_call_completed_groups(
    *, user_present: bool
) -> None:
    """No-provider input retains a repository call and only original User absence."""
    service = _service(providers=[], facts=(), user_present=user_present, failure=None)
    assert await service.get_user_credentials(user_id="user-id") == (
        [] if user_present else None
    )
    result = await service.get_login_projection(email="unknown@example.com")
    assert not result.has_password and not result.email_available
    assert isinstance(service.repository, SnapshotRepository)
    assert service.repository.user_reads == [("user-id", ())]
    assert service.repository.login_reads == [("unknown@example.com", ())]


async def test_initial_absence_skips_all_provider_projection() -> None:
    """Completed None is transparent and never invokes a pure provider."""
    provider = _fixed_provider(
        _summary(
            credential_type=CredentialType.PASSWORD,
            configured=False,
            valid=False,
            can_elevate=False,
            reason=CredentialUnavailableReason.NOT_CONFIGURED,
        ),
        failure=None,
    )
    service = _service(
        providers=[provider],
        facts=(),
        user_present=False,
        failure=None,
    )
    assert await service.get_security_projection(user_id="missing") is None
    assert await service.get_elevation_projection(user_id="missing") is None
    assert (
        await service.check_remove_allowed(
            user_id="missing", credential_type=CredentialType.PASSWORD
        )
        is None
    )
    assert not provider.observed_facts


@pytest.mark.parametrize("login", [False, True])
@pytest.mark.parametrize("kind_mismatch", [False, True])
async def test_broken_completed_fact_contract_is_not_silently_projected(
    *, login: bool, kind_mismatch: bool
) -> None:
    """Strict length and kind pairing protect the closed operation contract."""
    service = _service(
        providers=[PasswordCredentialProvider()],
        facts=(
            (CredentialReadFact(kind=CredentialReadKind.EMAIL, configured=True),)
            if kind_mismatch
            else ()
        ),
        user_present=True,
        failure=None,
    )
    with pytest.raises(ValueError):
        if login:
            await service.get_login_projection(email="submitted@example.com")
        else:
            await service.get_user_credentials(user_id="user-id")


@pytest.mark.parametrize("login", [False, True])
@pytest.mark.parametrize("provider_failure", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_completed_or_projection_failures_and_cancellation_propagate(
    *, login: bool, provider_failure: bool, cancelled: bool
) -> None:
    """No error conversion, retry or cancellation catch is added by orchestration."""
    error = asyncio.CancelledError() if cancelled else RuntimeError("read failure")
    provider = _fixed_provider(
        _summary(
            credential_type=CredentialType.PASSWORD,
            configured=True,
            valid=True,
            can_elevate=True,
            reason=None,
        ),
        failure=error if provider_failure else None,
    )
    service = _service(
        providers=[provider],
        facts=(CredentialReadFact(kind=CredentialReadKind.PASSWORD, configured=True),),
        user_present=True,
        failure=None if provider_failure else error,
    )
    with pytest.raises(type(error)) as result:
        if login:
            await service.get_login_projection(email="submitted@example.com")
        else:
            await service.get_user_credentials(user_id="user-id")
    assert result.value is error
    assert len(provider.observed_facts) == (1 if provider_failure else 0)
