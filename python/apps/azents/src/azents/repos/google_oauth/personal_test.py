"""User-owned Google publication using the existing staged grant lifecycle."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from azents.core.google_oauth import (
    GoogleAttempt,
    GoogleOAuthError,
    GooglePersonalSubject,
    GoogleReconnectSettings,
)
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.toolkit_ownership import (
    PersonalToolkitAccessMode,
    ToolkitOwnerKind,
    UserToolkitOwner,
)
from azents.rdb.models.google_oauth import RDBGoogleAttempt, RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.google_oauth.management_test import (
    Harness,
    _candidate,
    _google,
    _settings,
)
from azents.repos.toolkit import ToolkitRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


@dataclasses.dataclass(frozen=True)
class PersonalHarness:
    shared: Harness
    subject: GooglePersonalSubject


async def personal_harness(
    manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> PersonalHarness:
    """Keep setup registration doubles, with real User ownership and SQL publication."""
    shared = await _google(manager)
    async with manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email=f"google-{uuid4().hex}@example.test")
        )
    monkeypatch.setattr(
        shared.repo.sessions,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                user_id=user.id, is_revoked=False, is_expired=False
            )
        ),
    )
    return PersonalHarness(
        shared,
        GooglePersonalSubject(
            user.id,
            shared.subject.session_id,
            UserToolkitOwner(kind=ToolkitOwnerKind.USER, user_id=user.id),
        ),
    )


async def review(h: PersonalHarness, target: str | None) -> GoogleAttempt:
    attempt = await h.shared.repo.start(
        h.subject,
        registration=h.shared.registration,
        setup=h.shared.setup,
        target_toolkit_id=target,
    )
    assert attempt.subject == h.subject
    await h.shared.repo.claim(
        h.subject,
        attempt_id=attempt.id,
        nonce=h.shared.setup.state_nonce,
        registration=h.shared.registration,
    )
    return await h.shared.repo.stage(
        h.subject,
        attempt_id=attempt.id,
        registration=h.shared.registration,
        candidate=_candidate("personal-fixture-token"),
    )


async def test_personal_confirm_creates_user_global_default_all_and_exact_outcome(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmation publishes personal targets excluded from Workspace readers."""
    h = await personal_harness(rdb_session_manager, monkeypatch)
    attempt = await review(h, None)
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(sa.select(RDBGoogleConnection.id)) is None
        )
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert row is not None and row.workspace_id is None and row.agent_id is None
        assert (
            row.owner_kind is ToolkitOwnerKind.USER
            and row.owner_user_id == h.subject.user_id
        )
    first = await h.shared.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.shared.registration,
        settings=_settings(),
    )
    second = await h.shared.repo.confirm(
        h.subject, attempt_id=attempt.id, registration=None, settings=_settings()
    )
    assert first == second and first.current
    async with rdb_session_manager() as session:
        toolkit = await h.shared.repo.personal_toolkits.get_personal(
            session, user_id=h.subject.user_id, toolkit_id=first.toolkit_id
        )
        assert toolkit is not None and toolkit.owner == h.subject.owner
        assert toolkit.access_mode is PersonalToolkitAccessMode.ALL
        assert toolkit.config["security_risk_acknowledged"] is True
        assert await ToolkitRepository().get_shared_by_id(session, toolkit.id) is None
        assert await ToolkitRepository().get_by_id(session, toolkit.id) is None
        row = await session.read_session.get(RDBGoogleAttempt, attempt.id)
        assert (
            row is not None
            and row.encrypted_candidate is None
            and row.encrypted_setup is None
        )
    # The same initiator cannot route personal attempts through a shared target.
    with pytest.raises(GoogleOAuthError, match="not found"):
        await h.shared.repo.load(
            dataclasses.replace(h.shared.subject, user_id=h.subject.user_id), attempt.id
        )
    with pytest.raises(GoogleOAuthError, match="not found"):
        await h.shared.repo.saved(
            dataclasses.replace(h.shared.subject, user_id=h.subject.user_id),
            first.toolkit_id,
        )


async def test_personal_reconnect_preserves_allowance_and_current_settings(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacement changes grant identity while preserving owner and policy."""
    h = await personal_harness(rdb_session_manager, monkeypatch)
    attempt = await review(h, None)
    first = await h.shared.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.shared.registration,
        settings=_settings(),
    )
    async with rdb_session_manager() as session:
        await h.shared.repo.personal_toolkits.mutate_access(
            session,
            user_id=h.subject.user_id,
            mutation=PersonalToolkitAccessMutation(
                first.toolkit_id,
                PersonalToolkitAccessMode.SELECTED,
                frozenset(),
                frozenset(),
                PersonalToolkitAccessMode.ALL,
            ),
        )
    replacement = await review(h, first.toolkit_id)
    async with rdb_session_manager() as session:
        await h.shared.repo.personal_toolkits.update_personal(
            session,
            user_id=h.subject.user_id,
            toolkit_id=first.toolkit_id,
            update={
                "name": "Concurrent personal rename",
                "enabled": False,
                "always_expose_tools": True,
            },
        )
    settings = GoogleReconnectSettings(
        tasks=_settings().tasks, timeout=12.0, security_risk_acknowledged=True
    )
    changed = await h.shared.repo.confirm(
        h.subject,
        attempt_id=replacement.id,
        registration=h.shared.registration,
        settings=settings,
    )
    assert (
        changed.toolkit_id == first.toolkit_id
        and changed.connection_id != first.connection_id
    )
    async with rdb_session_manager() as session:
        current = await h.shared.repo.personal_toolkits.get_personal(
            session, user_id=h.subject.user_id, toolkit_id=first.toolkit_id
        )
        assert (
            current is not None
            and current.access_mode is PersonalToolkitAccessMode.SELECTED
        )
        assert (
            current.name == "Concurrent personal rename"
            and not current.enabled
            and current.always_expose_tools
        )
    historical = await h.shared.repo.outcome(h.subject, attempt.id)
    assert not historical.current


async def test_personal_disconnect_and_cancel_defeat_stale_publication(
    rdb_session_manager: SessionManager[WriteSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing canceled/reconnect target guards apply identically to User owners."""
    h = await personal_harness(rdb_session_manager, monkeypatch)
    abandoned = await review(h, None)
    assert await h.shared.repo.cancel(h.subject, abandoned.id) is None
    with pytest.raises(GoogleOAuthError, match="not ready"):
        await h.shared.repo.confirm(
            h.subject,
            attempt_id=abandoned.id,
            registration=h.shared.registration,
            settings=_settings(),
        )
    attempt = await review(h, None)
    published = await h.shared.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.shared.registration,
        settings=_settings(),
    )
    reconnect = await review(h, published.toolkit_id)
    await h.shared.repo.disconnect(h.subject, published.toolkit_id)
    with pytest.raises(GoogleOAuthError):
        await h.shared.repo.confirm(
            h.subject,
            attempt_id=reconnect.id,
            registration=h.shared.registration,
            settings=GoogleReconnectSettings(
                tasks=_settings().tasks, timeout=12.0, security_risk_acknowledged=True
            ),
        )
    saved = await h.shared.repo.saved(h.subject, published.toolkit_id)
    assert saved.connection is None
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.get(RDBToolkitConfig, published.toolkit_id)
        assert toolkit is not None and toolkit.owner_user_id == h.subject.user_id
