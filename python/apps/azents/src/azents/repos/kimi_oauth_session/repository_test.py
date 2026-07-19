"""Kimi OAuth session repository tests."""

import datetime
import uuid

from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.kimi_oauth import KimiOAuthConnectionMethod
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from .data import KimiOAuthSessionCreate
from .repository import KimiOAuthSessionRepository

_TEST_KEY = Fernet.generate_key().decode()


async def _create_session(
    session: AsyncSession,
) -> tuple[KimiOAuthSessionRepository, str]:
    """Create a pending Kimi OAuth session for tests."""
    suffix = uuid.uuid4().hex[:12]
    workspace_repo = WorkspaceRepository()
    workspace_result = await workspace_repo.create(
        session,
        WorkspaceCreate(
            name=f"Kimi OAuth test {suffix}",
            handle=f"kimi-oauth-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await workspace_repo.resolve_id(session, f"kimi-oauth-{suffix}")
    assert workspace_id is not None
    user = await UserRepository().create(
        session,
        UserCreate(email=f"kimi-oauth-{suffix}@example.com"),
    )
    repo = KimiOAuthSessionRepository(CredentialCipher(_TEST_KEY))
    created = await repo.create(
        session,
        KimiOAuthSessionCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            method=KimiOAuthConnectionMethod.DEVICE,
            device_code=f"device-{suffix}",
            device_id=f"device-id-{suffix}",
            user_code="ABCD-EFGH",
            verification_uri="https://auth.kimi.com/device",
            interval_seconds=5,
            expires_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=5),
        ),
    )
    return repo, created.id


async def test_increase_poll_interval_accumulates_slow_down(
    rdb_session: AsyncSession,
) -> None:
    """Apply the RFC 8628 five-second increment on every slow_down."""
    repo, session_id = await _create_session(rdb_session)

    first = await repo.increase_poll_interval(
        rdb_session,
        session_id,
        seconds=5,
    )
    second = await repo.increase_poll_interval(
        rdb_session,
        session_id,
        seconds=5,
    )

    assert isinstance(first, Success)
    assert first.value.interval_seconds == 10
    assert isinstance(second, Success)
    assert second.value.interval_seconds == 15
