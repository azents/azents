"""Concrete database-only Platform GitHub identity impact composition."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.github_system_setting import PlatformGitHubAppConfig
from azents.core.github_system_setting_data import (
    PlatformGitHubAppBindingState,
    PlatformGitHubAppImpact,
)
from azents.core.system_setting import ResolvedSystemSetting
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingRepository,
)
from azents.repos.github_platform_system_setting.data import (
    PlatformGitHubAppConfirmationImpact,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)


def _config(resolved: ResolvedSystemSetting) -> PlatformGitHubAppConfig:
    if not isinstance(resolved.config, PlatformGitHubAppConfig):
        raise TypeError("Unexpected Platform GitHub App config model.")
    return resolved.config


@dataclasses.dataclass(frozen=True)
class PlatformGitHubAppImpactRepository:
    """Complete inspection reads and compose locked confirmation impact."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    impact_repository: Annotated[
        PlatformGitHubAppSystemSettingRepository,
        Depends(PlatformGitHubAppSystemSettingRepository),
    ]
    bindings: Annotated[
        PlatformGitHubAppBindingRepository, Depends(PlatformGitHubAppBindingRepository)
    ]

    async def resolve_impact(
        self, current: ResolvedSystemSetting, candidate: ResolvedSystemSetting
    ) -> PlatformGitHubAppConfirmationImpact:
        """Finish impact inspection before external validation finalization."""
        async with self.session_manager() as session:
            return await self.resolve_impact_in_session(session, current, candidate)

    async def resolve_impact_in_session(
        self,
        session: AsyncSession,
        current: ResolvedSystemSetting,
        candidate: ResolvedSystemSetting,
    ) -> PlatformGitHubAppConfirmationImpact:
        current_config = _config(current)
        candidate_config = _config(candidate)
        app_id_changed = current_config.app_id != candidate_config.app_id
        if current_config.app_id is None:
            affected_user_count = 0
            affected_installation_count = 0
            affected_toolkit_ids: set[str] = set()
        else:
            installation_impact = await self.impact_repository.get_installation_impact(
                session,
                app_id=current_config.app_id,
            )
            toolkit_impact = await self.bindings.inspect_toolkits_bound_to(
                session,
                app_id=current_config.app_id,
            )
            affected_user_count = installation_impact.affected_user_count
            affected_installation_count = (
                installation_impact.affected_installation_count
            )
            affected_toolkit_ids = set(toolkit_impact.affected_toolkit_ids)
        affected_agent_count = await self.impact_repository.count_agents_for_toolkits(
            session,
            toolkit_ids=affected_toolkit_ids,
        )
        has_current_bindings = affected_installation_count > 0 or bool(
            affected_toolkit_ids
        )
        confirmation_actions = (
            ("activate",)
            if current_config.app_id is not None
            and app_id_changed
            and has_current_bindings
            else ()
        )
        impact = PlatformGitHubAppImpact(
            app_id_changed=app_id_changed,
            affected_user_count=affected_user_count,
            affected_installation_count=affected_installation_count,
            affected_toolkit_count=len(affected_toolkit_ids),
            affected_agent_count=affected_agent_count,
            current_app_id_source=current.field_sources["app_id"].value,
            confirmation_actions=confirmation_actions,
        )
        return PlatformGitHubAppConfirmationImpact.from_impact(impact)

    async def resolve_current_binding_impact(
        self,
        resolved: ResolvedSystemSetting,
    ) -> PlatformGitHubAppBindingState | None:
        app_id = _config(resolved).app_id
        if app_id is None:
            return None
        async with self.session_manager() as session:
            installation_impact = (
                await self.impact_repository.get_current_binding_installation_impact(
                    session,
                    effective_app_id=app_id,
                )
            )
            toolkit_impact = await self.bindings.inspect_toolkits_mismatched_with(
                session,
                effective_app_id=app_id,
            )
            affected_toolkit_ids = set(toolkit_impact.affected_toolkit_ids)
            affected_agent_count = (
                await self.impact_repository.count_agents_for_toolkits(
                    session,
                    toolkit_ids=affected_toolkit_ids,
                )
            )
        return PlatformGitHubAppBindingState(
            affected_user_count=installation_impact.affected_user_count,
            affected_installation_count=(
                installation_impact.affected_installation_count
            ),
            affected_toolkit_count=len(affected_toolkit_ids),
            affected_agent_count=affected_agent_count,
        )
