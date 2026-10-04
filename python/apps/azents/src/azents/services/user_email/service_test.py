"""UserEmail service projections and errors after completed database operations."""

from azcommon.result import Failure, Success

from azents.core.user_email import DuplicateEmail, UserEmailCreate
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.operations import UserEmailOperationRepository
from azents.repos.user_email.operations_test import ObservedEmailManager
from azents.services.user_email import UserEmailService
from azents.services.user_email.data import UserEmailOutput


async def test_service_projects_after_resolution_and_preserves_conflict_missing_results(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Email response conversion is session-free across all five service operations."""
    async with rdb_session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="email-service-primary@example.com")
        )
    manager = ObservedEmailManager(rdb_session_manager)
    service = UserEmailService(
        repository=UserEmailOperationRepository(manager, UserEmailRepository())
    )
    request = UserEmailCreate(user_id=user.id, email="email-service-extra@example.com")
    created = await service.create(request)
    assert isinstance(created, Success)
    assert isinstance(created.value, UserEmailOutput)
    assert created.value.verified_at is None
    assert await service.create(request) == Failure(DuplicateEmail(email=request.email))
    assert await service.get(created.value.id) == created.value
    assert await service.get("0" * 32) is None
    user_emails = await service.list_by_user(user.id)
    assert user_emails.total == len(user_emails.items) == 2
    page = await service.list_all(offset=0, limit=1)
    assert page.total == 2 and len(page.items) == 1
    await service.delete("0" * 32)
    await service.delete(created.value.id)
    assert await service.get(created.value.id) is None
    assert not manager.active
    assert manager.resolved == [True] * 9
