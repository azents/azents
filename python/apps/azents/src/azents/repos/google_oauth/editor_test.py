"""Atomic Google editor apply uses existing manager, revision and grant fences."""

import dataclasses

import pytest
import sqlalchemy as sa

from azents.core.google_oauth import (
    GoogleMetadataEdits,
    GoogleOAuthError,
    GoogleReconnectSettings,
)
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.google_oauth.management_test import _google, _review, _settings


def _metadata(revision: int, slug: str = "research") -> GoogleMetadataEdits:
    return GoogleMetadataEdits(
        expected_revision=revision,
        name="Research",
        slug=slug,
        description="Explicit apply",
        prompt=None,
        enabled=True,
        always_expose_tools=False,
    )


async def test_editor_applies_metadata_timeout_and_services_atomically(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    before = await h.repo.saved(h.subject, published.toolkit_id)
    await h.repo.update_services(
        h.subject,
        toolkit_id=published.toolkit_id,
        expected_revision=before.revision,
        services=(),
        tool_groups=before.tool_groups,
        timeout=12.0,
        metadata=_metadata(before.revision),
    )
    after = await h.repo.saved(h.subject, published.toolkit_id)
    assert after.connection == before.connection
    assert after.oauth_request_scopes == before.oauth_request_scopes
    assert after.timeout == 12 and after.services == ()
    assert after.revision == before.revision + 1
    async with rdb_session_manager() as session:
        row = await session.read_session.scalar(
            sa.select(RDBToolkitConfig).where(
                RDBToolkitConfig.id == published.toolkit_id
            )
        )
        assert row is not None
        assert (
            row.name == "Research"
            and row.description == "Explicit apply"
            and row.slug == "research"
        )


@pytest.mark.parametrize("slug,revision_delta", [("not/valid", 0), ("valid", 1)])
async def test_invalid_or_stale_metadata_rolls_back_all_editor_changes(
    rdb_session_manager: SessionManager[WriteSession],
    slug: str,
    revision_delta: int,
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    before = await h.repo.saved(h.subject, published.toolkit_id)
    with pytest.raises(GoogleOAuthError):
        await h.repo.update_services(
            h.subject,
            toolkit_id=published.toolkit_id,
            expected_revision=before.revision,
            services=(),
            tool_groups=(),
            timeout=12.0,
            metadata=_metadata(before.revision + revision_delta, slug),
        )
    assert await h.repo.saved(h.subject, published.toolkit_id) == before


async def test_reconnect_apply_publishes_metadata_and_grant_in_one_transaction(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    attempt = await _review(h, None)
    published = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    before = await h.repo.saved(h.subject, published.toolkit_id)
    replacement = await _review(h, published.toolkit_id)
    settings = GoogleReconnectSettings(
        **_settings().model_dump(
            include={"services", "tool_groups", "oauth_request_scopes", "timeout"}
        ),
        metadata=_metadata(before.revision),
    )
    result = await h.repo.confirm(
        h.subject,
        attempt_id=replacement.id,
        registration=h.registration,
        settings=settings,
    )
    assert result.connection_id != published.connection_id
    assert (
        await h.repo.confirm(
            h.subject,
            attempt_id=replacement.id,
            registration=h.registration,
            settings=settings,
        )
        == result
    )
    async with rdb_session_manager() as session:
        row = await session.read_session.scalar(
            sa.select(RDBToolkitConfig).where(
                RDBToolkitConfig.id == published.toolkit_id
            )
        )
        assert row is not None and row.name == "Research"
    # The wrong current owner cannot acquire the settings write.
    with pytest.raises(GoogleOAuthError):
        await h.repo.update_services(
            dataclasses.replace(h.subject, workspace_id="foreign"),
            toolkit_id=published.toolkit_id,
            expected_revision=before.revision + 1,
            services=(),
            tool_groups=(),
            timeout=None,
            metadata=None,
        )
