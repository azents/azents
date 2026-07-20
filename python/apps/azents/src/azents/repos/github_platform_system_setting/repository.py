"""Platform GitHub App System Settings impact repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig

from .data import PlatformGitHubAppImpact


class PlatformGitHubAppSystemSettingRepository:
    """Read redacted GitHub identity-change impact counts."""

    async def get_impact(
        self,
        session: AsyncSession,
        *,
        app_id_changed: bool,
    ) -> PlatformGitHubAppImpact:
        """Return current legacy resources affected by an App ID change."""
        platform_toolkits = sa.select(RDBToolkitConfig.id).where(
            RDBToolkitConfig.toolkit_type == "github",
            RDBToolkitConfig.config["github_auth_type"].astext == "github_app_platform",
        )
        affected_user_count = await session.scalar(
            sa.select(sa.func.count(sa.distinct(RDBGithubUserInstallation.user_id)))
        )
        affected_installation_count = await session.scalar(
            sa.select(sa.func.count()).select_from(RDBGithubUserInstallation)
        )
        affected_toolkit_count = await session.scalar(
            sa.select(sa.func.count()).select_from(platform_toolkits.subquery())
        )
        affected_agent_count = await session.scalar(
            sa.select(sa.func.count(sa.distinct(RDBAgentToolkit.agent_id))).where(
                RDBAgentToolkit.toolkit_id.in_(platform_toolkits)
            )
        )
        installation_count = affected_installation_count or 0
        toolkit_count = affected_toolkit_count or 0
        return PlatformGitHubAppImpact(
            app_id_changed=app_id_changed,
            affected_user_count=affected_user_count or 0,
            affected_installation_count=installation_count,
            affected_toolkit_count=toolkit_count,
            affected_agent_count=affected_agent_count or 0,
            unbound_installation_count=installation_count,
            unbound_toolkit_count=toolkit_count,
        )
