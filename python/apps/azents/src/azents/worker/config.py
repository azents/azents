"""Worker-local configuration objects."""

import dataclasses

from azents.engine.run.retry_policy import FailedRunRetryPolicy


@dataclasses.dataclass(frozen=True)
class AgentWorkerConfig:
    """Configuration values referenced directly by AgentWorker."""

    web_url: str
    oauth_secret_key: str
    mcp_proxy_url: str | None
    openai_responses_websocket_enabled: bool
    failed_run_retry_policy: FailedRunRetryPolicy
