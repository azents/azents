"""Completed read-only configuration capture for external-channel orchestration."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclass(frozen=True, kw_only=True)
class ExternalChannelHTTPAdmissionReadRepository:
    """Close the native read-only scope before authentication or provider work."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def get_slack_configuration(
        self, *, provider_app_id: str, provider_tenant_id: str
    ) -> ExternalChannelConnectionConfiguration | None:
        async with self.session_manager() as session:
            result = (
                await self.repository.get_slack_http_configuration_by_provider_identity(
                    session,
                    provider_app_id=provider_app_id,
                    provider_tenant_id=provider_tenant_id,
                )
            )
        return result

    async def get_discord_configuration(
        self, *, selector_hash: str
    ) -> ExternalChannelConnectionConfiguration | None:
        """Capture the exact Discord selector configuration before authentication."""
        async with self.session_manager() as session:
            result = (
                await self.repository.get_discord_http_configuration_by_selector_hash(
                    session, selector_hash=selector_hash
                )
            )
        return result
