"""Platform GitHub App System Settings repository data."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlatformGitHubAppImpact:
    """Redacted resources affected by a Platform GitHub App identity change."""

    app_id_changed: bool
    affected_user_count: int
    affected_installation_count: int
    affected_toolkit_count: int
    affected_agent_count: int
    unbound_installation_count: int
    unbound_toolkit_count: int

    @property
    def confirmation_required(self) -> bool:
        """Return whether activation requires an explicit Admin confirmation."""
        return self.app_id_changed and (
            self.affected_installation_count > 0 or self.affected_toolkit_count > 0
        )

    def to_metadata(self) -> dict[str, object]:
        """Return the bounded JSON-compatible impact representation."""
        return asdict(self)
