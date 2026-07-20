"""Platform GitHub App System Settings binding repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig

from .data import (
    PlatformGitHubAppInstallationImpact,
    PlatformGitHubAppToolkitCredential,
)


class PlatformGitHubAppSystemSettingRepository:
    """Read and update redacted GitHub identity bindings."""

    @staticmethod
    def _platform_toolkit_filter() -> tuple[sa.ColumnElement[bool], ...]:
        return (
            RDBToolkitConfig.toolkit_type == "github",
            RDBToolkitConfig.config["github_auth_type"].astext == "github_app_platform",
        )

    async def get_installation_impact(
        self,
        session: AsyncSession,
        *,
        current_app_id: str | None,
    ) -> PlatformGitHubAppInstallationImpact:
        """Return bound-current and unbound installation counts."""
        affected_filter = (
            RDBGithubUserInstallation.platform_app_id == current_app_id
            if current_app_id is not None
            else RDBGithubUserInstallation.platform_app_id.is_(None)
        )
        affected_user_count = await session.scalar(
            sa.select(sa.func.count(sa.distinct(RDBGithubUserInstallation.user_id)))
            .select_from(RDBGithubUserInstallation)
            .where(affected_filter)
        )
        affected_installation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBGithubUserInstallation)
            .where(affected_filter)
        )
        unbound_installation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBGithubUserInstallation)
            .where(RDBGithubUserInstallation.platform_app_id.is_(None))
        )
        return PlatformGitHubAppInstallationImpact(
            affected_user_count=affected_user_count or 0,
            affected_installation_count=affected_installation_count or 0,
            unbound_installation_count=unbound_installation_count or 0,
        )

    async def get_current_binding_installation_impact(
        self,
        session: AsyncSession,
        *,
        effective_app_id: str,
    ) -> PlatformGitHubAppInstallationImpact:
        """Return installation rows that cannot use the effective App identity."""
        affected_filter = sa.or_(
            RDBGithubUserInstallation.platform_app_id.is_(None),
            RDBGithubUserInstallation.platform_app_id != effective_app_id,
        )
        affected_user_count = await session.scalar(
            sa.select(sa.func.count(sa.distinct(RDBGithubUserInstallation.user_id)))
            .select_from(RDBGithubUserInstallation)
            .where(affected_filter)
        )
        affected_installation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBGithubUserInstallation)
            .where(affected_filter)
        )
        unbound_installation_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBGithubUserInstallation)
            .where(RDBGithubUserInstallation.platform_app_id.is_(None))
        )
        return PlatformGitHubAppInstallationImpact(
            affected_user_count=affected_user_count or 0,
            affected_installation_count=affected_installation_count or 0,
            unbound_installation_count=unbound_installation_count or 0,
        )

    async def list_platform_toolkit_credentials(
        self,
        session: AsyncSession,
    ) -> list[PlatformGitHubAppToolkitCredential]:
        """Return encrypted credentials for Platform GitHub Toolkits."""
        result = await session.execute(
            sa.select(
                RDBToolkitConfig.id,
                RDBToolkitConfig.encrypted_credentials,
            ).where(
                *self._platform_toolkit_filter(),
                RDBToolkitConfig.encrypted_credentials.is_not(None),
            )
        )
        return [
            PlatformGitHubAppToolkitCredential(
                toolkit_id=toolkit_id,
                encrypted_credentials=encrypted_credentials,
            )
            for toolkit_id, encrypted_credentials in result.all()
            if encrypted_credentials is not None
        ]

    async def count_agents_for_toolkits(
        self,
        session: AsyncSession,
        *,
        toolkit_ids: set[str],
    ) -> int:
        """Return distinct Agents attached to affected Platform Toolkits."""
        if not toolkit_ids:
            return 0
        count = await session.scalar(
            sa.select(sa.func.count(sa.distinct(RDBAgentToolkit.agent_id))).where(
                RDBAgentToolkit.toolkit_id.in_(toolkit_ids)
            )
        )
        return count or 0

    async def bind_unbound_installations(
        self,
        session: AsyncSession,
        *,
        app_id: str,
    ) -> int:
        """Bind every unbound legacy installation row to one App identity."""
        unbound = aliased(RDBGithubUserInstallation)
        bound = aliased(RDBGithubUserInstallation)
        duplicate_ids = sa.select(unbound.id).where(
            unbound.platform_app_id.is_(None),
            sa.exists(
                sa.select(bound.id).where(
                    bound.user_id == unbound.user_id,
                    bound.installation_id == unbound.installation_id,
                    bound.platform_app_id == app_id,
                )
            ),
        )
        deleted = await session.execute(
            sa.delete(RDBGithubUserInstallation)
            .where(RDBGithubUserInstallation.id.in_(duplicate_ids))
            .returning(RDBGithubUserInstallation.id)
        )
        updated = await session.execute(
            sa.update(RDBGithubUserInstallation)
            .where(RDBGithubUserInstallation.platform_app_id.is_(None))
            .values(platform_app_id=app_id)
            .returning(RDBGithubUserInstallation.id)
        )
        return len(deleted.scalars().all()) + len(updated.scalars().all())

    async def update_platform_toolkit_credentials(
        self,
        session: AsyncSession,
        *,
        toolkit_id: str,
        encrypted_credentials: str,
    ) -> None:
        """Replace one Platform Toolkit credential ciphertext."""
        await session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == toolkit_id)
            .values(encrypted_credentials=encrypted_credentials)
        )
