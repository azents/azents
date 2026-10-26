"""Exact setup-claim ownership checks at database and provider boundaries."""

import datetime

import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSetupClaimStatus,
    ExternalChannelSetupPreparationStatus,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelSetupPreparationBoundary,
)
from azents.core.external_channel_participation_state import (
    setup_source_from_projection,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelSetupClaim,
)
from azents.rdb.session_capabilities import ReadSession


def preparation_owned(
    claim: RDBExternalChannelSetupClaim,
    boundary: ExternalChannelSetupPreparationBoundary,
    *,
    now: datetime.datetime,
) -> bool:
    """Require current source, selection, execution ownership and expiry."""
    return (
        claim.status
        in (
            ExternalChannelSetupClaimStatus.PENDING_AGENT,
            ExternalChannelSetupClaimStatus.PENDING_LOCATION,
        )
        and claim.claim_generation == boundary.claim_generation
        and claim.source_revision == boundary.source_revision
        and claim.preparation_lease_owner == boundary.preparation_owner
        and claim.preparation_lease_until is not None
        and claim.preparation_lease_until > now
        and claim.expires_at > now
    )


async def setup_preparation_dispatch_current(
    session: ReadSession,
    *,
    boundary: ExternalChannelSetupPreparationBoundary,
    now: datetime.datetime,
) -> bool:
    """Revalidate exact preparation authority immediately before provider I/O."""
    row = await session.read_session.scalar(
        sa.select(RDBExternalChannelSetupClaim)
        .join(
            RDBExternalChannelConnection,
            RDBExternalChannelConnection.id
            == RDBExternalChannelSetupClaim.connection_id,
        )
        .where(
            RDBExternalChannelSetupClaim.id == boundary.claim_id,
            RDBExternalChannelSetupClaim.preparation_configuration_generation
            == boundary.configuration_generation,
            RDBExternalChannelConnection.configuration_generation
            == boundary.configuration_generation,
            RDBExternalChannelConnection.disconnected_at.is_(None),
            sa.or_(
                RDBExternalChannelSetupClaim.route_id.is_(None),
                sa.exists(
                    sa.select(RDBExternalChannelAgentRoute.id)
                    .join(
                        RDBAgent,
                        RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                    )
                    .where(
                        RDBExternalChannelAgentRoute.id
                        == RDBExternalChannelSetupClaim.route_id,
                        RDBExternalChannelAgentRoute.connection_id
                        == RDBExternalChannelSetupClaim.connection_id,
                        RDBExternalChannelAgentRoute.catalog_status
                        == ExternalChannelRouteCatalogStatus.AVAILABLE,
                        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                        ~sa.exists()
                        .where(
                            RDBExternalChannelBlock.agent_id == RDBAgent.id,
                            RDBExternalChannelBlock.principal_id
                            == RDBExternalChannelSetupClaim.principal_id,
                            RDBExternalChannelBlock.removed_at.is_(None),
                        )
                        .correlate(RDBAgent, RDBExternalChannelSetupClaim),
                    )
                    .correlate(RDBExternalChannelSetupClaim)
                ),
            ),
            ~sa.exists().where(
                RDBExternalChannelParticipationSetting.connection_id
                == RDBExternalChannelSetupClaim.connection_id,
                RDBExternalChannelParticipationSetting.provider_parent_channel_id
                == RDBExternalChannelSetupClaim.provider_parent_channel_id,
                RDBExternalChannelParticipationSetting.status
                == ExternalChannelParticipationSettingStatus.ACTIVE,
            ),
            ~sa.exists().where(
                RDBExternalChannelBinding.resource_id
                == RDBExternalChannelSetupClaim.source_resource_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            ),
        )
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or not preparation_owned(row, boundary, now=now)
        or row.preparation_status
        is not ExternalChannelSetupPreparationStatus.DISPATCHING
        or row.connection_id != boundary.connection_id
        or row.source_resource_id != boundary.source_resource_id
        or row.principal_id != boundary.principal_id
        or row.conversation_position_id != boundary.conversation_position_id
    ):
        return False
    source = setup_source_from_projection(row.source_projection)
    return (
        source.trigger_provider_message_key == boundary.trigger_provider_message_key
        and source.trigger_position == boundary.trigger_position
        and source.range_start_position == boundary.range_start_position
    )
