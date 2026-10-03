"""Pure Signup application and required completed-operation contract tests."""

import asyncio
import dataclasses
import datetime
import inspect
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from azcommon.logging import RuntimeEnvironment
from azcommon.result import Failure, Result, Success
from fastapi.params import Depends

from azents.core.config import Config, JWTConfig
from azents.core.email.service import EmailService
from azents.core.enums import SignupTokenDeliveryMethod
from azents.core.signup_token_operations import (
    InvalidSignupToken,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    SignupTokenRedeemCommand,
    SignupTokenRedeemFacts,
)
from azents.rdb.deps import get_session_manager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.signup_token import SignupTokenRepository
from azents.repos.signup_token.data import (
    SignupToken,
    SignupTokenCreate,
    SignupTokenList,
)
from azents.repos.signup_token_operations import SignupTokenOperationRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository
from azents.services import signup_token as application
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token import data as service_data
from azents.services.signup_token.data import (
    CreateSignupTokenInput,
    PreviewSignupTokenInput,
    RedeemSignupTokenInput,
    WeakSignupPassword,
)
from azents.services.signup_token.service_test import _TEST_AUTH_CONFIG

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class CompletedOperations(SignupTokenOperationRepository):
    """Return completed domain results only, without constructing SQL collaborators."""

    def __init__(
        self,
        *,
        lookup: SignupToken | None,
        redemption: Result[
            SignupTokenRedeemFacts,
            InvalidSignupToken
            | SignupTokenEmailMismatch
            | SignupTokenEmailAlreadyRegistered,
        ],
        revoked: bool,
        failure: BaseException | None,
    ) -> None:
        self.lookup = lookup
        self.redemption = redemption
        self.revoked = revoked
        self.failure = failure
        self.calls: list[str] = []
        self.creates: list[SignupTokenCreate] = []
        self.pages: list[tuple[int, int]] = []
        self.hashes: list[str] = []
        self.commands: list[SignupTokenRedeemCommand] = []
        self.revocations: list[str] = []

    async def create(self, *, create: SignupTokenCreate) -> SignupToken:
        """Model the completed create result, not commit/rollback or query behavior."""
        self.calls.append("create")
        self.creates.append(create)
        return SignupToken(
            id="token-id",
            token_hash=create.token_hash,
            email=create.email,
            created_by_user_id=create.created_by_user_id,
            delivery_method=create.delivery_method,
            expires_at=create.expires_at,
            max_uses=create.max_uses,
            used_count=0,
            revoked_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def list_all(self, *, offset: int, limit: int) -> SignupTokenList:
        """Return a detached list without simulating count/page SQL."""
        self.calls.append("list")
        self.pages.append((offset, limit))
        return SignupTokenList(items=[], total=0)

    async def get_by_token_hash(self, *, token_hash: str) -> SignupToken | None:
        """Record only completed lookup input."""
        self.calls.append("get")
        self.hashes.append(token_hash)
        return self.lookup

    async def redeem(
        self, *, command: SignupTokenRedeemCommand
    ) -> Result[
        SignupTokenRedeemFacts,
        InvalidSignupToken
        | SignupTokenEmailMismatch
        | SignupTokenEmailAlreadyRegistered,
    ]:
        """Return prepared success/failure without any SQL atomicity claim."""
        self.calls.append("redeem")
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return self.redemption

    async def revoke(self, *, token_id: str) -> bool:
        """Model the existing completed boolean contract only."""
        self.calls.append("revoke")
        self.revocations.append(token_id)
        return self.revoked


def _service(repository: SignupTokenOperationRepository) -> SignupTokenService:
    """Use required actual application collaborators with completed operations."""
    return SignupTokenService(
        operation_repository=repository,
        email_service=EmailService(config=None, ses_client=None),
        auth_config=_TEST_AUTH_CONFIG,
        config=Config.model_construct(
            runtime_env=RuntimeEnvironment.LOCAL,
            web_url="https://azents.example.com",
        ),
    )


def _input(*, password: str) -> RedeemSignupTokenInput:
    """Keep opaque token, normalized-email preparation and agent/IP explicit."""
    return RedeemSignupTokenInput(
        token="opaque-token",
        email="  NewUser@Example.COM ",
        password=password,
        user_agent="unit-agent",
        ip_address="127.0.0.1",
    )


def _repository(
    *,
    lookup: SignupToken | None,
    error: InvalidSignupToken
    | SignupTokenEmailMismatch
    | SignupTokenEmailAlreadyRegistered
    | None,
    failure: BaseException | None,
) -> CompletedOperations:
    """Construct a typed completed result double with every choice explicit."""
    redemption: Result[
        SignupTokenRedeemFacts,
        InvalidSignupToken
        | SignupTokenEmailMismatch
        | SignupTokenEmailAlreadyRegistered,
    ] = (
        Success(SignupTokenRedeemFacts(user_id="user-id", session_id="session-id"))
        if error is None
        else Failure(error)
    )
    return CompletedOperations(
        lookup=lookup, redemption=redemption, revoked=True, failure=failure
    )


def test_pure_required_frozen_values_and_canonical_error_definitions() -> None:
    """Expose only command fields, committed IDs and the single moved definitions."""
    assert [f.name for f in dataclasses.fields(SignupTokenRedeemCommand)] == [
        "token_hash",
        "now",
        "email",
        "password_hash",
        "refresh_token",
        "expires_at",
        "max_expires_at",
        "user_agent",
        "ip_address",
    ]
    assert [f.name for f in dataclasses.fields(SignupTokenRedeemFacts)] == [
        "user_id",
        "session_id",
    ]
    for defining_class in (
        SignupTokenRedeemCommand,
        SignupTokenRedeemFacts,
        InvalidSignupToken,
        SignupTokenEmailMismatch,
        SignupTokenEmailAlreadyRegistered,
    ):
        assert defining_class.__module__ == "azents.core.signup_token_operations"
        assert defining_class.__dataclass_params__.frozen
        assert all(
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
            for f in dataclasses.fields(defining_class)
        )
    assert [f.name for f in dataclasses.fields(SignupTokenEmailAlreadyRegistered)] == [
        "email"
    ]
    assert not dataclasses.fields(InvalidSignupToken)
    assert not dataclasses.fields(SignupTokenEmailMismatch)
    assert all(
        name not in vars(service_data)
        for name in (
            "InvalidSignupToken",
            "SignupTokenEmailMismatch",
            "SignupTokenEmailAlreadyRegistered",
        )
    )


def test_repository_service_required_fields_and_actual_canonical_dependencies() -> None:
    """Do not construct a Session or preserve an obsolete raw service constructor."""
    expected = {
        "session_manager": get_session_manager,
        "signup_token_repository": SignupTokenRepository,
        "user_repository": UserRepository,
        "user_email_repository": UserEmailRepository,
        "password_login_repository": PasswordLoginRepository,
        "session_repository": SessionRepository,
    }
    assert SignupTokenOperationRepository.__dataclass_params__.frozen
    hints = get_type_hints(SignupTokenOperationRepository, include_extras=True)
    assert list(hints) == list(expected)
    for name, dependency in expected.items():
        assert get_origin(hints[name]) is Annotated
        metadata = get_args(hints[name])[1]
        assert isinstance(metadata, Depends)
        assert metadata.dependency is dependency
    assert list(inspect.signature(SignupTokenService).parameters) == [
        "operation_repository",
        "email_service",
        "auth_config",
        "config",
    ]
    for defining_class in (SignupTokenOperationRepository, SignupTokenService):
        assert all(
            f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
            for f in dataclasses.fields(defining_class)
        )
    for method in (
        SignupTokenOperationRepository.create,
        SignupTokenOperationRepository.list_all,
        SignupTokenOperationRepository.get_by_token_hash,
        SignupTokenOperationRepository.redeem,
        SignupTokenOperationRepository.revoke,
    ):
        for name, parameter in inspect.signature(method).parameters.items():
            if name != "self":
                assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
                assert parameter.default is inspect.Parameter.empty


async def test_create_defaults_and_normalization_before_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep configured defaults, nullable actor and hash-free public metadata."""
    repository = _repository(lookup=None, error=None, failure=None)
    service = _service(repository)
    monkeypatch.setattr(application, "tznow", lambda: _NOW)
    monkeypatch.setattr(application, "generate_signup_token", lambda: "opaque-token")
    result = await service.create(
        CreateSignupTokenInput(
            email=" NewUser@Example.COM ",
            created_by_user_id=None,
            delivery_method=SignupTokenDeliveryMethod.MANUAL,
            expires_at=None,
            max_uses=None,
        )
    )
    assert repository.calls == ["create"]
    create = repository.creates[0]
    assert create.email == "newuser@example.com"
    assert create.token_hash == application.hash_signup_token("opaque-token")
    assert create.created_by_user_id is None
    assert create.expires_at == _NOW + datetime.timedelta(hours=168)
    assert create.max_uses == 1
    assert result.plaintext_token == "opaque-token"
    assert "token_hash" not in result.token.model_dump()
    assert "plaintext_token" not in result.token.model_dump()


async def test_weak_password_precedes_token_hash_and_opens_no_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid token cannot outrank the original weak-password precondition."""
    repository = _repository(lookup=None, error=InvalidSignupToken(), failure=None)

    def unexpected_hash(token: str) -> str:
        raise AssertionError("Weak password must precede token hashing.")

    monkeypatch.setattr(application, "hash_signup_token", unexpected_hash)
    result = await _service(repository).redeem(_input(password="weak"))
    assert not result.success
    assert isinstance(result.error, WeakSignupPassword)
    assert not repository.calls


async def test_exact_preparation_order_captured_clock_and_committed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure preparation forwards all nine fields and JWT uses only completed IDs."""
    events: list[str] = []
    repository = _repository(lookup=None, error=None, failure=None)
    service = _service(repository)

    def strength(password: str) -> None:
        events.append("strength")

    def token_hash(token: str) -> str:
        events.append("token_hash")
        return "prepared-token-hash"

    def now() -> datetime.datetime:
        events.append("now")
        return _NOW

    def password_hash(password: str) -> str:
        events.append("password_hash")
        return "prepared-password-hash"

    def refresh_token() -> str:
        events.append("refresh")
        return "prepared-refresh"

    def jwt(*, config: JWTConfig, user_id: str, session_id: str) -> str:
        assert config is service.auth_config.jwt
        assert user_id == "user-id" and session_id == "session-id"
        assert repository.calls == ["redeem"]
        events.append("jwt")
        return "post-operation-jwt"

    monkeypatch.setattr(application, "validate_password_strength", strength)
    monkeypatch.setattr(application, "hash_signup_token", token_hash)
    monkeypatch.setattr(application, "tznow", now)
    monkeypatch.setattr(application, "hash_password", password_hash)
    monkeypatch.setattr(application, "generate_refresh_token", refresh_token)
    monkeypatch.setattr(application, "create_access_token", jwt)
    result = await service.redeem(_input(password="StrongPass123!"))
    assert result.success
    assert events == [
        "strength",
        "token_hash",
        "now",
        "password_hash",
        "refresh",
        "jwt",
    ]
    command = repository.commands[0]
    assert command == SignupTokenRedeemCommand(
        token_hash="prepared-token-hash",
        now=_NOW,
        email="newuser@example.com",
        password_hash="prepared-password-hash",
        refresh_token="prepared-refresh",
        expires_at=_NOW + service.auth_config.refresh_token.expire_timedelta,
        max_expires_at=None,
        user_agent="unit-agent",
        ip_address="127.0.0.1",
    )
    assert command.now is _NOW
    assert result.value.access_token == "post-operation-jwt"
    assert result.value.refresh_token == "prepared-refresh"
    assert (
        result.value.expires_in == service.auth_config.jwt.access_token_expire_seconds
    )


@pytest.mark.parametrize(
    "error",
    [
        InvalidSignupToken(),
        SignupTokenEmailMismatch(),
        SignupTokenEmailAlreadyRegistered(email="newuser@example.com"),
    ],
)
async def test_expected_operation_error_identity_and_no_jwt(
    error: InvalidSignupToken
    | SignupTokenEmailMismatch
    | SignupTokenEmailAlreadyRegistered,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application wrapping retains the exact canonical failure object."""
    repository = _repository(lookup=None, error=error, failure=None)

    def unexpected_jwt(*, config: JWTConfig, user_id: str, session_id: str) -> str:
        raise AssertionError("Denied operation must not create a JWT.")

    monkeypatch.setattr(application, "create_access_token", unexpected_jwt)
    result = await _service(repository).redeem(_input(password="StrongPass123!"))
    assert not result.success and result.error is error
    assert repository.calls == ["redeem"]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_completed_operation_error_or_cancel_is_transparent(
    *, cancelled: bool
) -> None:
    """Typed doubles prove no application retry/conversion, not SQL cancellation."""
    error = asyncio.CancelledError() if cancelled else RuntimeError("database error")
    repository = _repository(lookup=None, error=None, failure=error)
    with pytest.raises(type(error)) as result:
        await _service(repository).redeem(_input(password="StrongPass123!"))
    assert result.value is error
    assert repository.calls == ["redeem"]


async def test_jwt_error_does_not_repeat_completed_redemption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a completed success, application failure adds no retry or compensation."""
    repository = _repository(lookup=None, error=None, failure=None)
    error = RuntimeError("JWT preparation failed")

    def failed_jwt(*, config: JWTConfig, user_id: str, session_id: str) -> str:
        raise error

    monkeypatch.setattr(application, "create_access_token", failed_jwt)
    with pytest.raises(RuntimeError) as result:
        await _service(repository).redeem(_input(password="StrongPass123!"))
    assert result.value is error
    assert repository.calls == ["redeem"]


async def test_list_default_page_forwarding_and_revoke_boolean() -> None:
    """No factory adapter, new list defaults or missing-row policy is introduced."""
    repository = _repository(lookup=None, error=None, failure=None)
    service = _service(repository)
    assert (await service.list_all()).total == 0
    assert repository.pages == [(0, 50)]
    assert await service.revoke("exact-token")
    repository.revoked = False
    assert not await service.revoke("absent-token")
    assert repository.revocations == ["exact-token", "absent-token"]


@pytest.mark.parametrize(
    "case", ["missing", "revoked", "expired", "exhausted", "valid"]
)
async def test_preview_original_absence_predicates_and_mask(
    *, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a completed exact lookup precedes the unchanged detached predicates."""
    token = SignupToken(
        id="token-id",
        token_hash=application.hash_signup_token("opaque-token"),
        email="newuser@example.com",
        created_by_user_id=None,
        delivery_method=SignupTokenDeliveryMethod.MANUAL,
        expires_at=_NOW if case == "expired" else _NOW + datetime.timedelta(hours=1),
        max_uses=1,
        used_count=1 if case == "exhausted" else 0,
        revoked_at=_NOW if case == "revoked" else None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repository = _repository(
        lookup=None if case == "missing" else token, error=None, failure=None
    )
    monkeypatch.setattr(application, "tznow", lambda: _NOW)
    result = await _service(repository).preview(
        PreviewSignupTokenInput(token="opaque-token")
    )
    assert repository.calls == ["get"]
    assert repository.hashes == [application.hash_signup_token("opaque-token")]
    if case == "valid":
        assert result.valid
        assert result.email == "n***@example.com"
        assert result.expires_at == token.expires_at
    else:
        assert not result.valid
        assert result.email is None and result.expires_at is None
