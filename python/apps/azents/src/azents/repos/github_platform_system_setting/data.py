"""Typed Platform GitHub App confirmation-impact boundary."""

from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from azents.core.github_system_setting_data import PlatformGitHubAppImpact


class PlatformGitHubAppConfirmationImpact(BaseModel):
    """Validated identity-impact snapshot used by confirmation decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    app_id_changed: bool
    affected_user_count: int
    affected_installation_count: int
    affected_toolkit_count: int
    affected_agent_count: int
    current_app_id_source: str
    confirmation_actions: tuple[str, ...]
    confirmation_required: bool

    @field_validator("confirmation_actions", mode="before")
    @classmethod
    def decode_actions(cls, value: object) -> object:
        """Restore the JSON array emitted by this snapshot's persistence boundary."""
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        """Require the confirmation marker to agree with the available actions."""
        if self.confirmation_required != bool(self.confirmation_actions):
            raise ValueError("Confirmation marker and available actions disagree.")
        return self

    @classmethod
    def from_impact(
        cls, impact: PlatformGitHubAppImpact
    ) -> "PlatformGitHubAppConfirmationImpact":
        """Keep typed domain evidence typed until storage or response egress."""
        return cls(
            app_id_changed=impact.app_id_changed,
            affected_user_count=impact.affected_user_count,
            affected_installation_count=impact.affected_installation_count,
            affected_toolkit_count=impact.affected_toolkit_count,
            affected_agent_count=impact.affected_agent_count,
            current_app_id_source=impact.current_app_id_source,
            confirmation_actions=impact.confirmation_actions,
            confirmation_required=impact.confirmation_required,
        )
