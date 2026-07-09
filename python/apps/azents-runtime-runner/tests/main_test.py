"""Runtime Runner entrypoint configuration tests."""

import pytest

from azents_runtime_runner.main import run_runtime_runner


@pytest.mark.asyncio
async def test_runner_requires_auth_credential_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner startup requires the provider-injected credential identifier."""
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_ID", "runtime-1")
    monkeypatch.setenv("AZ_AGENT_WORKSPACE_PATH", "/workspace/agent")
    monkeypatch.delenv("AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID", raising=False)

    with pytest.raises(SystemExit, match="AZ_RUNTIME_RUNNER_AUTH_CREDENTIAL_ID"):
        await run_runtime_runner()
