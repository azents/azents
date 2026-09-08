"""EmailVerificationService tests."""

from unittest.mock import AsyncMock

from azents.repos.email_verification.data import EmailVerificationList
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)

from . import EmailVerificationService


async def test_list_all_uses_completed_operation_repository() -> None:
    """Administrative Email Verification reads do not receive a live session."""
    operation_repository = AsyncMock(spec=EmailVerificationOperationRepository)
    operation_repository.list_all.return_value = EmailVerificationList(
        items=[],
        total=0,
    )
    service = EmailVerificationService(
        email_verification_operation_repository=operation_repository
    )

    result = await service.list_all(offset=3, limit=7)

    assert result.items == []
    assert result.total == 0
    operation_repository.list_all.assert_awaited_once_with(offset=3, limit=7)
