"""Worker-local configuration objects."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class AgentWorkerConfig:
    """Configuration values referenced directly by AgentWorker."""

    web_url: str
    oauth_secret_key: str
    mcp_proxy_url: str | None
