"""Provider preparation and Session creation for ingress conversation owners."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationPreparation,
    ExternalChannelConversationProvisioningError,
)
from azents.repos.external_channel.ingress_queue_data import ExternalChannelIngressOwner
from azents.services.external_channel.conversation_provisioning import (
    ExternalChannelConversationProvisioningService,
)

ExternalChannelIngressProvisioningError = ExternalChannelConversationProvisioningError
ExternalChannelIngressProviderPreparation = ExternalChannelConversationPreparation


@dataclasses.dataclass
class ExternalChannelIngressProvisioningService:
    """Prepare one provider conversation before creating its Binding and Session."""

    conversation_provisioning: Annotated[
        ExternalChannelConversationProvisioningService,
        Depends(ExternalChannelConversationProvisioningService),
    ]

    async def prepare(
        self,
        *,
        owner: ExternalChannelIngressOwner,
    ) -> ExternalChannelIngressProviderPreparation:
        """Perform provider I/O without creating any Azents Session state."""
        return await self.conversation_provisioning.prepare(
            connection_id=owner.connection_id,
            target_resource_id=owner.target_resource_id,
        )
