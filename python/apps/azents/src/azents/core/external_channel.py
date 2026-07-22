"""External Channel domain value types."""

from typing import TypedDict

from azents.core.enums import ExternalChannelWorkTaskStatus


class ExternalChannelWorkTask(TypedDict):
    """One ordered task in a binding-scoped Channel Work payload."""

    key: str
    content: str
    status: ExternalChannelWorkTaskStatus
