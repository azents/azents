"""Worker-local configuration objects."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class AgentWorkerConfig:
    """Configuration values referenced directly by AgentWorker."""

    web_url: str
    oauth_secret_key: str
    mcp_proxy_url: str | None
    xai_oauth_client_id: str | None
    failed_run_max_retries: int
    failed_run_base_backoff_seconds: int
    failed_run_backoff_multiplier: int
    failed_run_max_backoff_seconds: int
