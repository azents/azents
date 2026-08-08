"""Agent process environment construction tests."""

import pytest

from azents_runtime_runner.environment import build_agent_environment


def test_agent_environment_keeps_only_safe_runner_values() -> None:
    environment = build_agent_environment(
        workspace_path="/workspace/agent",
        operation_environment={"GITHUB_TOKEN": "tool-token"},
        source_environment={
            "PATH": "/usr/local/bin:/usr/bin",
            "LANG": "en_US.UTF-8",
            "AZ_RUNTIME_RUNNER_AUTH_TOKEN": "runner-secret",
            "UNRELATED_SECRET": "secret",
        },
    )

    assert environment == {
        "PATH": "/usr/local/bin:/usr/bin",
        "LANG": "en_US.UTF-8",
        "HOME": "/workspace/agent",
        "SHELL": "/bin/bash",
        "TMPDIR": "/tmp",
        "GITHUB_TOKEN": "tool-token",
    }


@pytest.mark.parametrize(
    "name",
    [
        "HOME",
        "PATH",
        "TMPDIR",
        "AZ_RUNTIME_RUNNER_AUTH_TOKEN",
        "AZENTS_RUNTIME_INTERNAL",
    ],
)
def test_agent_environment_rejects_reserved_operation_names(name: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        build_agent_environment(
            workspace_path="/workspace/agent",
            operation_environment={name: "override"},
            source_environment={},
        )
