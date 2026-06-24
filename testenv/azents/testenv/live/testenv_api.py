"""Testenv devtools API client."""

from dataclasses import dataclass

import httpx

from testenv.runtime_config import TestenvConfig


@dataclass(frozen=True)
class TestenvApi:
    """Thin client for testenv-only HTTP helpers."""

    config: TestenvConfig

    def inject_resume(self, session_id: str, agent_id: str) -> None:
        """Inject a RESUME message into the broker."""
        url = f"{self.config.testenv_api_url}/broker/v1/inject-resume"
        response = httpx.post(
            url,
            json={"session_id": session_id, "agent_id": agent_id},
            timeout=10.0,
        )
        response.raise_for_status()
