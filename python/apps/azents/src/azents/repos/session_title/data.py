"""Session title operation repository data models."""

import dataclasses

from azents.core.model_operation import ModelOperationSnapshot


@dataclasses.dataclass(frozen=True)
class SessionTitleGenerationSnapshot:
    """Durable candidate operation needed for one automatic title attempt."""

    agent_id: str
    workspace_id: str
    operation: ModelOperationSnapshot
