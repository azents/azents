"""Tests for provider identity OAuth attempt retention."""

import datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from azents.core.crypto import CredentialCipher
from azents.core.external_account_oauth import EXTERNAL_ACCOUNT_OAUTH_RETENTION
from azents.repos.external_account_oauth.data import (
    ExternalAccountOAuthAttemptCleanupSummary,
)
from azents.services.external_account_oauth.service import (
    ExternalAccountOAuthAttemptService,
)

_NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


@pytest.mark.asyncio
async def test_cleanup_expired_uses_the_bounded_oauth_retention_cutoff() -> None:
    """Attempt cleanup deletes only rows older than the diagnostic retention window."""
    repository = cast(Any, AsyncMock())
    repository.cleanup.return_value = ExternalAccountOAuthAttemptCleanupSummary(
        deleted_count=3
    )
    service = ExternalAccountOAuthAttemptService(
        repository=repository,
        cipher=cast(CredentialCipher, object()),
    )

    result = await service.cleanup_expired(now=_NOW, limit=500)

    assert result.deleted_count == 3
    repository.cleanup.assert_awaited_once_with(
        cutoff=_NOW - EXTERNAL_ACCOUNT_OAUTH_RETENTION,
        limit=500,
    )
