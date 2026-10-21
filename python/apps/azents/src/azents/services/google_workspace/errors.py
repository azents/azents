"""Failed compound operations retain confirmed steps without claiming success."""

from pydantic import BaseModel, ConfigDict

from azents.services.google_workspace.transport import GoogleSdkError


class GoogleCompletedStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: str
    resource_ids: tuple[str, ...]


class GooglePartialOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    completed: tuple[GoogleCompletedStep, ...]
    unconfirmed_action: str
    remaining_ids: tuple[str, ...]
    cause_code: str


class GoogleWorkspacePartialError(GoogleSdkError):
    """Raised, not returned as a successful response containing an error field."""

    def __init__(
        self,
        *,
        completed: tuple[GoogleCompletedStep, ...],
        unconfirmed_action: str,
        remaining_ids: tuple[str, ...],
        cause_code: str,
        status: int | None,
        dispatched: bool,
    ) -> None:
        self.partial = GooglePartialOperation(
            completed=completed,
            unconfirmed_action=unconfirmed_action,
            remaining_ids=remaining_ids,
            cause_code=cause_code,
        )
        super().__init__("partial_operation", dispatched=dispatched, status=status)
