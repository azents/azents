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
    ExternalChannelInvocationWakeDispatcher,
)
from azents.services.external_channel.ingestion_history import (
    ExternalChannelProviderHistoryReader,
)
from azents.services.external_channel.ingestion_store import (
    ExternalChannelDatabaseIngestionStore,
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
        ExternalChannelDatabaseIngestionStore,
        Depends(ExternalChannelDatabaseIngestionStore),
    ],
    wake_dispatcher: Annotated[
        ExternalChannelInvocationWakeDispatcher,
        Depends(ExternalChannelInvocationWakeDispatcher),
    ],
) -> ExternalChannelConversationIngestionService:
    """Compose the shared ingestion service for transport and replay callers."""
    return ExternalChannelConversationIngestionService(
        conversation_lock=conversation_lock,
        history_reader=history_reader,
        store=store,
        wake_dispatcher=wake_dispatcher,
    )
