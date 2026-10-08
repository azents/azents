"""Signup preparation and post-commit application effects around real SQL groups."""

import asyncio
import dataclasses
from collections.abc import Callable
from datetime import datetime, timedelta
from unittest.mock import create_autospec
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from types_aiobotocore_ses.client import SESClient

import azents.api.public.auth.v1 as auth_api
import azents.services.signup_token as signup_module
from azents.api.public.auth.v1.data import (
    RedeemSignupTokenRequest,
    RedeemSignupTokenResponse,
    RequestSignupEmailRequest,
)
from azents.core.auth.jwt import decode_access_token
from azents.core.config import (
    AuthConfig,
    Config,
    EmailConfig,
    JWTConfig,
    RefreshTokenConfig,
    RegistrationMode,
    SignupTokenConfig,
)
from azents.core.email.deps import create_template_environment
from azents.core.email.service import EmailService
from azents.core.enums import SignupTokenDeliveryMethod
from azents.core.signup_token_operations import (
    InvalidSignupToken,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    SignupTokenRedeemCommand,
    SignupTokenRedeemFacts,
)
from azents.rdb.models.signup_token import RDBSignupToken
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.signup_token.data import (
    SignupToken,
    SignupTokenCreate,
    SignupTokenList,
)
from azents.repos.signup_token_operations import SignupTokenOperationRepository
from azents.repos.signup_token_operations_test import (
    NOW,
    ActualRollbackPasswords,
    IndependentSignupManager,
    SignupFixture,
    SignupScope,
    cleanup_signup,
    footprint,
    seed_token,
    signup_fixture,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token.data import (
    CreateSignupTokenInput,
    PreviewSignupTokenInput,
    RedeemSignupTokenInput,
    SignupEmailDeliveryUnavailable,
    SignupTokenOutput,
    SignupTokenWithPlaintextOutput,
    WeakSignupPassword,
)


@dataclasses.dataclass(frozen=True)
class ClosedSignupOperations(SignupTokenOperationRepository):
    """Forward actual completed operations, then observe closure without fake SQL."""

    scope: SignupScope
    events: list[str]
    commands: list[SignupTokenRedeemCommand]
    pause_after_redeem: bool
    completed: asyncio.Event
    release: asyncio.Event

    async def create(self, *, create: SignupTokenCreate) -> SignupToken:
        self.scope.assert_closed()
        self.events.append("db_create")
        result = await super().create(create=create)
        self.scope.assert_closed()
        self.events.append("closed_create")
        return result

    async def list_all(self, *, offset: int, limit: int) -> SignupTokenList:
        self.scope.assert_closed()
        self.events.append("db_list")
        result = await super().list_all(offset=offset, limit=limit)
        self.scope.assert_closed()
        self.events.append("closed_list")
        return result

    async def get_by_token_hash(self, *, token_hash: str) -> SignupToken | None:
        self.scope.assert_closed()
        self.events.append("db_preview")
        result = await super().get_by_token_hash(token_hash=token_hash)
        self.scope.assert_closed()
        self.events.append("closed_preview")
        return result

    async def redeem(
        self, *, command: SignupTokenRedeemCommand
    ) -> Result[
        SignupTokenRedeemFacts,
        InvalidSignupToken
        | SignupTokenEmailMismatch
        | SignupTokenEmailAlreadyRegistered,
    ]:
        self.scope.assert_closed()
        self.events.append("db_redeem")
        self.commands.append(command)
        result = await super().redeem(command=command)
        self.scope.assert_closed()
        self.events.append("closed_redeem")
        if isinstance(result, Success) and self.pause_after_redeem:
            self.completed.set()
            await self.release.wait()
        return result


class ClosedSignupEmail(EmailService):
    """Real configured/render path; transport outcome is an explicit local double."""

    def __init__(
        self, scope: SignupScope, events: list[str], *, configured: bool, mode: str
    ) -> None:
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
        super().__init__(
            config=config,
            ses_client=create_autospec(SESClient, instance=True)
            if configured
            else None,
            template_environment=create_template_environment(),
        )
        self.scope = scope
        self.events = events
        self.mode = mode
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def configured(self) -> bool:
        self.scope.assert_closed()
        self.events.append("configured")
        return super().configured

    def _render_template(self, template_name: str, **kwargs: object) -> str:
        self.scope.assert_closed()
        self.events.append("render")
        return super()._render_template(template_name, **kwargs)

    async def _send_email(
        self, *, to_email: str, subject: str, html_body: str, text_body: str
    ) -> None:
        self.scope.assert_closed()
        assert to_email and subject and html_body and text_body
        self.events.append("transport_double")
        self.reached.set()
        if self.mode == "error":
            raise RuntimeError("synthetic transport failed after committed create")
        if self.mode == "cancel":
            await self.release.wait()

    async def send_signup_token(
        self, *, to_email: str, signup_url: str, expire_hours: int, language: str = "ko"
    ) -> bool:
        self.scope.assert_closed()
        if self.mode == "false":
            self.events.append("send_false_double")
            return False
        return await super().send_signup_token(
            to_email=to_email,
            signup_url=signup_url,
            expire_hours=expire_hours,
            language=language,
        )


class ClosedSignupService(SignupTokenService):
    def __init__(
        self,
        repository: ClosedSignupOperations,
        email: ClosedSignupEmail,
        auth: AuthConfig,
        config: Config,
        events: list[str],
    ) -> None:
        super().__init__(
            operation_repository=repository,
            email_service=email,
            auth_config=auth,
            config=config,
        )
        self.scope = repository.scope
        self.events = events

    def build_signup_url(self, token: str) -> str:
        self.scope.assert_closed()
        self.events.append("url")
        return super().build_signup_url(token)


def synthetic_config() -> Config:
    """Explicit validated test settings; never load production environment values."""
    return Config.model_validate(
        {
            "runtime_env": "local",
            "sentry_dsn": None,
            "rdb": {
                "host": "unused.example.test",
                "port": 5432,
                "user": "unused",
                "password": None,
                "db_name": "unused",
            },
            "auth": {
                "jwt": {"secret_key": "synthetic-only"},
                "refresh_token": {},
                "signup_token": {},
            },
            "system_bootstrap": {"setup_token": None},
            "runtime_provider_bootstrap": {
                "source_key": None,
                "source_path": None,
                "poll_interval_seconds": 10.0,
            },
            "email": None,
            "credential_encryption": {"key": "synthetic-only"},
            "redis": {"url": "redis://unused.example.test"},
            "runtime_transfer_coordinator": {
                "endpoint": None,
                "tls_ca_file": None,
                "allow_insecure": False,
                "credential_lifetime_seconds": 60.0,
            },
            "model_stream_timeout": {
                "connect_timeout_seconds": 10.0,
                "parsed_event_idle_timeout_seconds": 10.0,
                "absolute_attempt_timeout_seconds": 30.0,
                "close_grace_seconds": 1.0,
            },
            "openai_responses_websocket_enabled": False,
            "workspace_s3": {"bucket": "unused"},
            "web_url": "https://web.example.test",
        }
    )


@dataclasses.dataclass(frozen=True)
class SignupBoundary:
    fixture: SignupFixture
    repository: ClosedSignupOperations
    service: ClosedSignupService
    email: ClosedSignupEmail
    events: list[str]


def boundary(
    fixture: SignupFixture,
    *,
    smtp: bool,
    mode: str,
    registration_mode: RegistrationMode,
    max_days: int | None,
    pause: bool,
) -> SignupBoundary:
    events: list[str] = []
    raw = fixture.repository
    repository = ClosedSignupOperations(
        session_manager=raw.session_manager,
        signup_token_repository=raw.signup_token_repository,
        user_repository=raw.user_repository,
        user_email_repository=raw.user_email_repository,
        password_login_repository=raw.password_login_repository,
        session_repository=raw.session_repository,
        scope=fixture.scope,
        events=events,
        commands=[],
        pause_after_redeem=pause,
        completed=asyncio.Event(),
        release=asyncio.Event(),
    )
    email = ClosedSignupEmail(fixture.scope, events, configured=smtp, mode=mode)
    auth = AuthConfig(
        jwt=JWTConfig(
            secret_key="synthetic-signing-key-never-production-0123456789abcdef"
        ),
        refresh_token=RefreshTokenConfig(expire_days=10, max_expire_days=max_days),
        signup_token=SignupTokenConfig(default_expire_hours=48, default_max_uses=2),
        registration_mode=registration_mode,
    )
    return SignupBoundary(
        fixture,
        repository,
        ClosedSignupService(repository, email, auth, synthetic_config(), events),
        email,
        events,
    )


@dataclasses.dataclass(frozen=True)
class PreparationProbe:
    password_hashes: list[str]
    refresh_tokens: list[str]
    clock_samples: list[datetime]
    jwt_ids: list[tuple[str, str]]


def observe_preparation(
    monkeypatch: pytest.MonkeyPatch,
    state: SignupBoundary,
    *,
    real_bcrypt: bool,
    advance_after_hash: bool,
    jwt_error: bool,
) -> PreparationProbe:
    fixture, events = state.fixture, state.events
    hashes: list[str] = []
    refreshes: list[str] = []
    samples: list[datetime] = []
    jwt_ids: list[tuple[str, str]] = []
    clock_value = [NOW]
    strength = signup_module.validate_password_strength
    token_hash = signup_module.hash_signup_token
    normalize = signup_module.normalize_signup_email
    bcrypt_hash = signup_module.hash_password
    refresh = signup_module.generate_refresh_token
    token_rng = signup_module.generate_signup_token
    jwt = signup_module.create_access_token
    mask = signup_module.mask_signup_email

    def validate(password: str) -> None:
        fixture.scope.assert_closed()
        events.append("strength")
        strength(password)

    def hash_token(value: str) -> str:
        fixture.scope.assert_closed()
        events.append("token_hash")
        return token_hash(value)

    def clock() -> datetime:
        fixture.scope.assert_closed()
        events.append("clock")
        samples.append(clock_value[0])
        return clock_value[0]

    def email(value: str) -> str:
        fixture.scope.assert_closed()
        events.append("normalize")
        return normalize(value)

    def password_hash(value: str) -> str:
        fixture.scope.assert_closed()
        events.append("bcrypt")
        result = (
            bcrypt_hash(value) if real_bcrypt else "synthetic-prepared-bcrypt-double"
        )
        hashes.append(result)
        if advance_after_hash:
            clock_value[0] = NOW + timedelta(days=2)
        return result

    def refresh_token() -> str:
        fixture.scope.assert_closed()
        events.append("refresh_rng")
        result = refresh()
        refreshes.append(result)
        return result

    def create_token() -> str:
        fixture.scope.assert_closed()
        events.append("token_rng")
        return token_rng()

    def create_jwt(
        *, config: JWTConfig, user_id: str, session_id: str, elevated: bool = False
    ) -> str:
        fixture.scope.assert_closed()
        events.append("jwt")
        jwt_ids.append((user_id, session_id))
        if jwt_error:
            raise RuntimeError("synthetic JWT failure after committed redemption")
        return jwt(
            config=config, user_id=user_id, session_id=session_id, elevated=elevated
        )

    def mask_email(value: str) -> str:
        fixture.scope.assert_closed()
        events.append("mask")
        return mask(value)

    monkeypatch.setattr(signup_module, "validate_password_strength", validate)
    monkeypatch.setattr(signup_module, "hash_signup_token", hash_token)
    monkeypatch.setattr(signup_module, "tznow", clock)
    monkeypatch.setattr(signup_module, "normalize_signup_email", email)
    monkeypatch.setattr(signup_module, "hash_password", password_hash)
    monkeypatch.setattr(signup_module, "generate_refresh_token", refresh_token)
    monkeypatch.setattr(signup_module, "generate_signup_token", create_token)
    monkeypatch.setattr(signup_module, "create_access_token", create_jwt)
    monkeypatch.setattr(signup_module, "mask_signup_email", mask_email)
    return PreparationProbe(hashes, refreshes, samples, jwt_ids)


async def token_for_service(fixture: SignupFixture) -> str:
    plaintext = f"synthetic-signup-{uuid4().hex}"
    await seed_token(
        fixture, token_hash=signup_module.hash_signup_token(plaintext), max_uses=1
    )
    return plaintext


def redeem_input(state: SignupBoundary, plaintext: str) -> RedeemSignupTokenInput:
    return RedeemSignupTokenInput(
        token=plaintext,
        email=f"  {state.fixture.email.upper()}  ",
        password="SyntheticStrong!42",
        user_agent="synthetic-agent",
        ip_address="192.0.2.17",
    )


@pytest.fixture
async def signup_boundary_pg(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> SignupFixture:
    return signup_fixture(rdb_session_manager, monkeypatch)


@pytest.mark.parametrize("variant", ["defaults", "custom", "falsy"])
async def test_actual_create_preparation_metadata_list_after_closed_sql(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    fixture = signup_boundary_pg
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="closed",
        max_days=None,
        pause=False,
    )
    observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    converted: list[str] = []

    class ClosedMetadata(SignupTokenOutput):
        def model_post_init(self, context: object) -> None:
            fixture.scope.assert_closed()
            converted.append("metadata")
            super().model_post_init(context)

    monkeypatch.setattr(signup_module, "SignupTokenOutput", ClosedMetadata)
    expires = NOW + timedelta(days=7) if variant == "custom" else None
    max_uses = 4 if variant == "custom" else 0 if variant == "falsy" else None
    result = await state.service.create(
        CreateSignupTokenInput(
            email=f"  {fixture.email.upper()}  ",
            created_by_user_id=None,
            delivery_method=SignupTokenDeliveryMethod.MANUAL,
            expires_at=expires,
            max_uses=max_uses,
        )
    )
    assert result.token.email == fixture.email
    assert result.token.expires_at == (
        expires if expires is not None else NOW + timedelta(hours=48)
    )
    assert result.token.max_uses == (4 if variant == "custom" else 2)
    assert (
        "token_hash" not in result.token.model_dump()
        and "plaintext_token" not in result.token.model_dump()
    )
    rows = await footprint(fixture)
    assert rows["tokens"][0]["token_hash"] == signup_module.hash_signup_token(
        result.plaintext_token
    )
    assert state.events[:6] == [
        "token_rng",
        "token_hash",
        "clock",
        "normalize",
        "db_create",
        "closed_create",
    ]
    listing = await state.service.list_all()
    assert listing.total == 1 and len(listing.items) == 1
    assert "token_hash" not in listing.items[0].model_dump()
    assert converted == ["metadata", "metadata"]
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "status",
    ["valid", "missing", "revoked", "expiry_equal", "expiry_past", "exhausted"],
)
async def test_actual_preview_clock_hash_mask_after_closed_read_and_no_consumption(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    fixture = signup_boundary_pg
    plaintext = await token_for_service(fixture)
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    probe = observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    async with fixture.manager() as session:
        if status == "revoked":
            await session.write_session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.email == fixture.email)
                .values(revoked_at=NOW)
            )
        elif status in {"expiry_equal", "expiry_past"}:
            await session.write_session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.email == fixture.email)
                .values(
                    expires_at=NOW
                    if status == "expiry_equal"
                    else NOW - timedelta(microseconds=1)
                )
            )
        elif status == "exhausted":
            await session.write_session.execute(
                sa.update(RDBSignupToken)
                .where(RDBSignupToken.email == fixture.email)
                .values(used_count=1)
            )
    before = await footprint(fixture)
    result = await state.service.preview(
        PreviewSignupTokenInput(token="missing" if status == "missing" else plaintext)
    )
    assert result.valid is (status == "valid")
    if status == "valid":
        assert (
            result.email == "s***@example.test"
            and result.expires_at == NOW + timedelta(hours=1)
        )
        assert state.events == [
            "token_hash",
            "clock",
            "db_preview",
            "closed_preview",
            "mask",
        ]
    else:
        assert result.email is result.expires_at is None
        assert state.events == ["token_hash", "clock", "db_preview", "closed_preview"]
    assert probe.clock_samples == [NOW] and probe.jwt_ids == []
    assert await footprint(fixture) == before
    fixture.scope.assert_closed()


@pytest.mark.parametrize("max_days", [None, 30])
async def test_actual_redeem_prepared_clock_before_bcrypt_and_jwt_after_commit(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
    max_days: int | None,
) -> None:
    fixture = signup_boundary_pg
    plaintext = await token_for_service(fixture)
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="closed",
        max_days=max_days,
        pause=False,
    )
    probe = observe_preparation(
        monkeypatch, state, real_bcrypt=True, advance_after_hash=True, jwt_error=False
    )
    result = await state.service.redeem(redeem_input(state, plaintext))
    assert isinstance(result, Success)
    assert state.events == [
        "strength",
        "token_hash",
        "clock",
        "normalize",
        "bcrypt",
        "refresh_rng",
        "db_redeem",
        "closed_redeem",
        "jwt",
    ]
    command = state.repository.commands[0]
    assert command.now == NOW and fixture.fault.clocks == [NOW, NOW]
    assert (
        command.email == fixture.email
        and command.password_hash == probe.password_hashes[0]
    )
    assert (
        command.refresh_token == result.value.refresh_token == probe.refresh_tokens[0]
    )
    assert command.expires_at == NOW + timedelta(days=10)
    assert command.max_expires_at == (
        NOW + timedelta(days=max_days) if max_days else None
    )
    assert (
        command.user_agent == "synthetic-agent" and command.ip_address == "192.0.2.17"
    )
    assert probe.clock_samples == [NOW]
    rows = await footprint(fixture)
    assert rows["tokens"][0]["used_count"] == 1
    assert rows["passwords"][0]["password_hash"] == command.password_hash
    assert rows["emails"][0]["verified_at"] == rows["audits"][0]["redeemed_at"] == NOW
    payload = decode_access_token(
        state.service.auth_config.jwt, result.value.access_token
    )
    assert (payload.user_id, payload.session_id) == probe.jwt_ids[0]
    assert (
        payload.user_id == rows["users"][0]["id"]
        and payload.session_id == rows["sessions"][0]["id"]
    )
    fixture.scope.assert_closed()


async def test_weak_password_precedes_bad_token_and_opens_zero_sql(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = signup_boundary_pg
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    probe = observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    result = await state.service.redeem(
        RedeemSignupTokenInput(
            token="missing",
            email=fixture.email,
            password="weak",
            user_agent=None,
            ip_address=None,
        )
    )
    assert isinstance(result, Failure) and isinstance(result.error, WeakSignupPassword)
    assert state.events == ["strength"]
    assert fixture.scope.sessions == [] and state.repository.commands == []
    assert (
        probe.password_hashes
        == probe.refresh_tokens
        == probe.clock_samples
        == probe.jwt_ids
        == []
    )


@pytest.mark.parametrize(
    "reason", ["invalid", "mismatch", "registered", "password_rollback"]
)
async def test_actual_expected_sql_failures_close_and_issue_no_jwt(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    fixture = signup_boundary_pg
    plaintext = await token_for_service(fixture)
    if reason == "registered":
        async with fixture.manager() as session:
            await UserRepository().create(session, UserCreate(email=fixture.email))
    if reason == "password_rollback":
        fixture = dataclasses.replace(
            fixture,
            repository=dataclasses.replace(
                fixture.repository,
                password_login_repository=ActualRollbackPasswords(fixture.fault),
            ),
        )
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    probe = observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    input = redeem_input(state, "missing" if reason == "invalid" else plaintext)
    if reason == "mismatch":
        input = input.model_copy(update={"email": "different@example.test"})
    before = await footprint(fixture)
    result = await state.service.redeem(input)
    assert isinstance(result, Failure)
    if reason == "invalid":
        assert isinstance(result.error, InvalidSignupToken)
    elif reason == "mismatch":
        assert isinstance(result.error, SignupTokenEmailMismatch)
    else:
        assert result.error == SignupTokenEmailAlreadyRegistered(email=fixture.email)
    assert probe.jwt_ids == [] and state.events[-1] == "closed_redeem"
    assert await footprint(fixture) == before
    fixture.scope.assert_closed()


@pytest.mark.parametrize(
    "stage", ["claim", "user_create", "password_create", "session_create", "audit"]
)
@pytest.mark.parametrize("cancel", [False, True])
async def test_service_real_postwrite_fault_cancel_closes_before_any_jwt(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    cancel: bool,
) -> None:
    fixture = signup_boundary_pg
    plaintext = await token_for_service(fixture)
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    probe = observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    before = await footprint(fixture)
    fixture.fault.stage, fixture.fault.pause = stage, cancel
    if not cancel:
        fixture.fault.error = RuntimeError("actual service postwrite fault")
    task = asyncio.create_task(state.service.redeem(redeem_input(state, plaintext)))
    try:
        if cancel:
            await asyncio.wait_for(fixture.fault.reached.wait(), timeout=10)
            task.cancel("after real selected Signup write")
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert probe.jwt_ids == [] and fixture.scope.failures == 1
        fixture.scope.assert_closed()
        assert await footprint(fixture) == before
    finally:
        fixture.fault.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("effect", ["jwt_error", "cancel_before_jwt"])
async def test_postcommit_jwt_failure_cancel_retains_independently_committed_group(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    effect: str,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with (
        rdb_engine.connect() as writer_connection,
        rdb_engine.connect() as observer_connection,
    ):
        writer, observer = (
            IndependentSignupManager(writer_connection),
            IndependentSignupManager(observer_connection),
        )
        fixture = signup_fixture(writer, monkeypatch)
        state = boundary(
            fixture,
            smtp=False,
            mode="ok",
            registration_mode="signup_token",
            max_days=None,
            pause=effect == "cancel_before_jwt",
        )
        plaintext = await token_for_service(fixture)
        probe = observe_preparation(
            monkeypatch,
            state,
            real_bcrypt=False,
            advance_after_hash=False,
            jwt_error=effect == "jwt_error",
        )
        task = asyncio.create_task(state.service.redeem(redeem_input(state, plaintext)))
        try:
            if effect == "cancel_before_jwt":
                await asyncio.wait_for(state.repository.completed.wait(), timeout=10)
                fixture.scope.assert_closed()
                task.cancel("after committed repo returned before synchronous JWT")
            with pytest.raises(
                asyncio.CancelledError
                if effect == "cancel_before_jwt"
                else RuntimeError
            ):
                await task
            observed = await footprint(dataclasses.replace(fixture, manager=observer))
            assert {name: len(values) for name, values in observed.items()} == {
                "tokens": 1,
                "users": 1,
                "emails": 1,
                "passwords": 1,
                "sessions": 1,
                "audits": 1,
            }
            assert observed["tokens"][0]["used_count"] == 1
            assert len(probe.jwt_ids) == (1 if effect == "jwt_error" else 0)
            assert writer.pids[-1] != observer.pids[-1]
            record_property("write_backend_pid", writer.pids[-1])
            record_property("observer_backend_pid", observer.pids[-1])
            record_property(
                "commit_witness",
                "fresh_connection_sees_whole_group_after_application_failure",
            )
            fixture.scope.assert_closed()
        finally:
            state.repository.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await cleanup_signup(fixture)


@pytest.mark.parametrize("mode", ["ok", "false", "error", "cancel"])
async def test_email_render_send_outcomes_after_close_retain_real_committed_token(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    record_property: Callable[[str, object], None],
) -> None:
    del latest_db_schema
    async with (
        rdb_engine.connect() as writer_connection,
        rdb_engine.connect() as observer_connection,
    ):
        writer, observer = (
            IndependentSignupManager(writer_connection),
            IndependentSignupManager(observer_connection),
        )
        fixture = signup_fixture(writer, monkeypatch)
        state = boundary(
            fixture,
            smtp=True,
            mode=mode,
            registration_mode="closed",
            max_days=None,
            pause=False,
        )
        observe_preparation(
            monkeypatch,
            state,
            real_bcrypt=False,
            advance_after_hash=False,
            jwt_error=False,
        )
        task = asyncio.create_task(
            state.service.create_email_delivery_token(fixture.email)
        )
        try:
            if mode == "cancel":
                await asyncio.wait_for(state.email.reached.wait(), timeout=10)
                task.cancel("after committed create during transport double")
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif mode == "error":
                with pytest.raises(RuntimeError, match="synthetic transport failed"):
                    await task
            elif mode == "false":
                with pytest.raises(
                    SignupEmailDeliveryUnavailable, match="did not complete"
                ):
                    await task
            else:
                result = await task
                assert isinstance(result, SignupTokenWithPlaintextOutput)
            observed = await footprint(dataclasses.replace(fixture, manager=observer))
            assert (
                len(observed["tokens"]) == 1
                and observed["tokens"][0]["used_count"] == 0
            )
            assert all(
                observed[name] == []
                for name in ("users", "emails", "passwords", "sessions", "audits")
            )
            assert (
                observed["tokens"][0]["delivery_method"]
                == SignupTokenDeliveryMethod.EMAIL
            )
            assert state.events.index("closed_create") < state.events.index("url")
            if mode != "false":
                assert state.events.count("render") == 2
                assert (
                    state.events.index("closed_create")
                    < state.events.index("render")
                    < state.events.index("transport_double")
                )
            assert writer.pids[-1] != observer.pids[-1]
            record_property("write_backend_pid", writer.pids[-1])
            record_property("observer_backend_pid", observer.pids[-1])
            record_property(
                "commit_witness",
                "fresh_connection_sees_token_after_named_delivery_outcome",
            )
            fixture.scope.assert_closed()
        finally:
            state.email.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await cleanup_signup(fixture)


async def test_unavailable_email_raises_without_create_or_send(
    signup_boundary_pg: SignupFixture,
) -> None:
    fixture = signup_boundary_pg
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    with pytest.raises(SignupEmailDeliveryUnavailable, match="not configured"):
        await auth_api.request_signup_email(
            state.service, RequestSignupEmailRequest(email=fixture.email)
        )
    assert state.events == ["configured"] and fixture.scope.sessions == []
    assert fixture.fault.trace == []


@pytest.mark.parametrize("mode", ["unconfigured", "false", "error"])
async def test_signup_email_uses_native_server_error_boundary(
    signup_boundary_pg: SignupFixture,
    mode: str,
) -> None:
    """Native HTTP failures reveal no transport text or plaintext token."""
    fixture = signup_boundary_pg
    state = boundary(
        fixture,
        smtp=mode != "unconfigured",
        mode="ok" if mode == "unconfigured" else mode,
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    app = FastAPI()
    app.include_router(auth_api.router)
    app.dependency_overrides[SignupTokenService] = lambda: state.service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://signup.test",
    ) as client:
        response = await client.post("/signup/email", json={"email": fixture.email})
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    if mode == "unconfigured":
        assert state.events == ["configured"]
        assert fixture.scope.sessions == [] and fixture.fault.trace == []
    observed = await footprint(fixture)
    assert len(observed["tokens"]) == (0 if mode == "unconfigured" else 1)
    assert all(token["revoked_at"] is None for token in observed["tokens"])
    fixture.scope.assert_closed()


@pytest.mark.parametrize("mode", ["signup_token", "closed", "open"])
async def test_original_get_mode_smtp_vs_post_smtp_only_behavior(
    signup_boundary_pg: SignupFixture,
    mode: RegistrationMode,
) -> None:
    fixture = signup_boundary_pg
    state = boundary(
        fixture,
        smtp=True,
        mode="ok",
        registration_mode=mode,
        max_days=None,
        pause=False,
    )
    status = await auth_api.get_signup_status(state.service.auth_config, state.email)
    assert status.email_signup_available is (mode == "signup_token")
    sent = await auth_api.request_signup_email(
        state.service, RequestSignupEmailRequest(email=fixture.email)
    )
    assert sent.sent is True
    assert len((await footprint(fixture))["tokens"]) == 1
    fixture.scope.assert_closed()


async def test_actual_public_redeem_response_conversion_follows_completed_sql(
    signup_boundary_pg: SignupFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = signup_boundary_pg
    plaintext = await token_for_service(fixture)
    state = boundary(
        fixture,
        smtp=False,
        mode="ok",
        registration_mode="signup_token",
        max_days=None,
        pause=False,
    )
    observe_preparation(
        monkeypatch, state, real_bcrypt=False, advance_after_hash=False, jwt_error=False
    )
    projected: list[str] = []

    class ClosedResponse(RedeemSignupTokenResponse):
        def model_post_init(self, context: object) -> None:
            fixture.scope.assert_closed()
            projected.append("public_response")
            super().model_post_init(context)

    monkeypatch.setattr(auth_api, "RedeemSignupTokenResponse", ClosedResponse)
    request = Request(
        {
            "type": "http",
            "headers": [(b"user-agent", b"synthetic-agent")],
            "client": ("192.0.2.17", 1234),
        }
    )
    result = await auth_api.redeem_signup_token(
        state.service,
        RedeemSignupTokenRequest(
            token=plaintext, email=fixture.email, password="SyntheticStrong!42"
        ),
        request,
    )
    assert projected == ["public_response"]
    assert result.access_token and result.refresh_token and result.expires_in == 1800
    assert (
        "password_hash" not in result.model_dump()
        and "token_hash" not in result.model_dump()
    )
    fixture.scope.assert_closed()
