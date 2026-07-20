"""Platform GitHub App System Settings repository data."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlatformGitHubAppToolkitCredential:
    """Encrypted Platform Toolkit credential selected for identity inspection."""

    toolkit_id: str
    encrypted_credentials: str


@dataclass(frozen=True)
class PlatformGitHubAppInstallationImpact:
    """Redacted installation counts for one App identity comparison."""

    affected_user_count: int
    affected_installation_count: int


@dataclass(frozen=True)
class PlatformGitHubAppImpact:
    """Redacted resources affected by a Platform GitHub App identity change."""

    app_id_changed: bool
    affected_user_count: int
    affected_installation_count: int
    affected_toolkit_count: int
    affected_agent_count: int
    current_app_id_source: str
    confirmation_actions: tuple[str, ...]

    @property
    def confirmation_required(self) -> bool:
        """Return whether activation requires an explicit Admin confirmation."""
        return bool(self.confirmation_actions)

    def to_metadata(self) -> dict[str, object]:
        """Return the bounded JSON-compatible impact representation."""
        metadata = asdict(self)
        metadata["confirmation_actions"] = list(self.confirmation_actions)
        return metadata
