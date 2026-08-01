"""Dependency composition for synchronous conversation ingestion."""

from typing import Annotated

from fastapi import Depends

from azents.services.external_channel.conversation import (
    ExternalChannelConversationLock,
)
from azents.services.external_channel.deps import (
    get_external_channel_conversation_lock,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
)
from azents.services.external_channel.ingestion_history import (
    ExternalChannelProviderHistoryReader,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
)
from azents.services.external_channel.mailbox_wake import (
    ExternalChannelMailboxWakeDispatcher,
)


def get_external_channel_conversation_ingestion_service(
    conversation_lock: Annotated[
        ExternalChannelConversationLock,
        Depends(get_external_channel_conversation_lock),
    ],
    history_reader: Annotated[
        ExternalChannelProviderHistoryReader,
        Depends(ExternalChannelProviderHistoryReader),
    ],
    store: Annotated[
        ExternalChannelMailboxIngestionStore,
        Depends(ExternalChannelMailboxIngestionStore),
    ],
    wake_dispatcher: Annotated[
        ExternalChannelMailboxWakeDispatcher,
        Depends(ExternalChannelMailboxWakeDispatcher),
    ],
) -> ExternalChannelConversationIngestionService:
    """Compose the shared ingestion service for transport and replay callers."""
    return ExternalChannelConversationIngestionService(
        conversation_lock=conversation_lock,
        history_reader=history_reader,
        store=store,
        wake_dispatcher=wake_dispatcher,
    )
