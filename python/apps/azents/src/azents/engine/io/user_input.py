"""Event user input types passed to engine runs."""

import dataclasses

from azents.engine.events.types import UserMessagePayload


@dataclasses.dataclass(frozen=True)
class RunUserMessage:
    """Event user message input included in RunRequest."""

    payload: UserMessagePayload
    external_id: str
