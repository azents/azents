"""WorkspaceService tests."""

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.workspace import WorkspaceService
from azents.services.workspace.data import (
    BootstrapFirstOwnerInput,
    BootstrapNotAvailable,
)

_TEST_AUTH_CONFIG = AuthConfig(
    jwt=JWTConfig(
        secret_key="test-secret-key-for-jwt-signing-1234567890",
        algorithm="HS256",
        access_token_expire_minutes=30,
    ),
    refresh_token=RefreshTokenConfig(
        expire_days=180,
        rotation_period_minutes=10,
        grace_period_minutes=5,
    ),
    signup_token=SignupTokenConfig(default_expire_hours=168, default_max_uses=1),
)


def _make_service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    auth_config: AuthConfig = _TEST_AUTH_CONFIG,
) -> WorkspaceService:
    """Create WorkspaceService for tests."""
    return WorkspaceService(
        workspace_repository=WorkspaceRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        user_repository=UserRepository(),
        password_login_repository=PasswordLoginRepository(),
        session_manager=rdb_session_manager,
        auth_config=auth_config,
    )


class TestWorkspaceServiceBootstrap:
    """WorkspaceService bootstrap tests."""

    async def test_bootstrap_first_owner_creates_user_workspace_owner(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Perform first owner bootstrap when User count is 0."""
        service = _make_service(rdb_session_manager)

        result = await service.bootstrap_first_owner(
            BootstrapFirstOwnerInput(
                email="owner@example.com",
                password="Aa123456!",
                owner_name="Owner",
                workspace_name="Owner Workspace",
                workspace_handle="owner-workspace",
                locale="ko-KR",
            )
        )

        assert isinstance(result, Success)
        assert result.value.workspace_handle == "owner-workspace"
        async with rdb_session_manager() as session:
            assert await UserRepository().count(session) == 1
            user = await UserRepository().get_by_email(session, "owner@example.com")
            assert user is not None
            workspace_id = await WorkspaceRepository().resolve_id(
                session,
                "owner-workspace",
            )
            assert workspace_id is not None
            workspace_user = await WorkspaceUserRepository().get_by_workspace_and_user(
                session,
                workspace_id,
                user.id,
            )
            assert workspace_user is not None
            assert workspace_user.role.value == "owner"

    async def test_bootstrap_first_owner_rejects_when_disabled(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject first owner bootstrap when configuration is disabled."""
        service = _make_service(
            rdb_session_manager,
            auth_config=_TEST_AUTH_CONFIG.model_copy(
                update={"first_owner_bootstrap_enabled": False}
            ),
        )

        result = await service.bootstrap_first_owner(
            BootstrapFirstOwnerInput(
                email="disabled@example.com",
                password="Aa123456!",
                owner_name="Owner",
                workspace_name="Disabled Workspace",
                workspace_handle="disabled-workspace",
                locale="ko-KR",
            )
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, BootstrapNotAvailable)

    async def test_bootstrap_first_owner_rejects_when_user_exists(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Reject first owner bootstrap when User count is 1 or more."""
        service = _make_service(rdb_session_manager)
        first = await service.bootstrap_first_owner(
            BootstrapFirstOwnerInput(
                email="owner2@example.com",
                password="Aa123456!",
                owner_name="Owner",
                workspace_name="Owner Workspace 2",
                workspace_handle="owner-workspace-2",
                locale="ko-KR",
            )
        )
        assert isinstance(first, Success)

        second = await service.bootstrap_first_owner(
            BootstrapFirstOwnerInput(
                email="owner3@example.com",
                password="Aa123456!",
                owner_name="Owner",
                workspace_name="Owner Workspace 3",
                workspace_handle="owner-workspace-3",
                locale="ko-KR",
            )
        )

        assert isinstance(second, Failure)
        assert isinstance(second.error, BootstrapNotAvailable)
