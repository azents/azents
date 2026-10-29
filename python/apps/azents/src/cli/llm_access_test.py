"""Operator CLI preserves the existing token lifecycle and secret custody."""

import datetime
import json
import stat
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from azents_llm_contract.authority import IssuedToken
from pydantic import SecretStr
from typer.testing import CliRunner

from azents.core.llm_access import LLMAccessDenied, LLMTokenConflict, SupplyState
from cli import llm_access

SECRET = "operator-token-secret-sentinel"
NOW = datetime.datetime(2026, 10, 29, tzinfo=datetime.timezone.utc)


@dataclass
class Config:
    runtime_env: str = "test"
    sentry_dsn: str | None = None


class Service:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.failure: Exception | None = None
        self.issued = IssuedToken(
            supply_id="supply",
            token_id="token",
            agent_token=SecretStr(SECRET),
            expires_at=NOW + datetime.timedelta(hours=1),
            predecessor_expires_at=None,
        )
        self.state = SupplyState(
            supply_id="supply",
            agent_id="agent",
            subject="development",
            issuer="operator_cli",
            current_token_id="token",
            revoked_at=None,
            tokens=(),
        )

    async def issue(self, **kwargs: object) -> IssuedToken:
        self.calls.append({"command": "issue", **kwargs})
        if self.failure is not None:
            raise self.failure
        return self.issued

    async def rotate(self, **kwargs: object) -> IssuedToken:
        self.calls.append({"command": "rotate", **kwargs})
        if self.failure is not None:
            raise self.failure
        return self.issued

    async def inspect(self, **kwargs: object) -> SupplyState:
        self.calls.append({"command": "inspect", **kwargs})
        return self.state

    async def inspect_subject(self, **kwargs: object) -> SupplyState:
        self.calls.append({"command": "lookup", **kwargs})
        return self.state

    async def revoke(self, **kwargs: object) -> None:
        self.calls.append({"command": "revoke", **kwargs})


class Container:
    def __init__(self, service: Service) -> None:
        self.service = service

    async def solve(self, kind: type[object]) -> Service:
        assert kind is llm_access.LLMAccessService
        return self.service


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    value = Service()
    monkeypatch.setattr(llm_access.Config, "from_env", Config)
    monkeypatch.setattr(
        llm_access, "configure_logging_for_runtime", lambda **kwargs: None
    )

    @asynccontextmanager
    async def container(config: Config) -> AsyncGenerator[Container]:
        yield Container(value)

    monkeypatch.setattr(llm_access, "run_with_container", container)
    return value


@pytest.mark.parametrize("rotate", [False, True])
def test_issue_and_rotate_write_only_private_new_file(
    service: Service, tmp_path: Path, rotate: bool
) -> None:
    output = tmp_path / "credential.json"
    command = (
        ["rotate", "--supply-id", "supply", "--expected-token-id", "old"]
        if rotate
        else ["issue", "--agent-id", "agent", "--subject", "development"]
    )
    result = CliRunner().invoke(llm_access.app, [*command, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert SECRET not in result.output
    assert json.loads(result.stdout)["token_id"] == "token"
    assert "agent_token" not in json.loads(result.stdout)
    assert json.loads(output.read_text())["agent_token"] == SECRET
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert service.calls == (
        [{"command": "rotate", "supply_id": "supply", "expected_token_id": "old"}]
        if rotate
        else [
            {
                "command": "issue",
                "agent_id": "agent",
                "subject": "development",
                "issuer": "operator_cli",
            }
        ]
    )


@pytest.mark.parametrize("destination", ["existing", "symlink", "missing-parent"])
def test_output_failure_precedes_mutation(
    service: Service, tmp_path: Path, destination: str
) -> None:
    output = tmp_path / "credential.json"
    if destination == "existing":
        output.write_text("keep")
    elif destination == "symlink":
        original = tmp_path / "original"
        original.write_text("keep")
        output.symlink_to(original)
    else:
        output = tmp_path / "missing" / "credential.json"
    result = CliRunner().invoke(
        llm_access.app,
        [
            "issue",
            "--agent-id",
            "agent",
            "--subject",
            "development",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 2
    assert service.calls == []
    if destination != "missing-parent":
        assert output.read_text() == "keep"


@pytest.mark.parametrize("failure", [LLMAccessDenied, LLMTokenConflict])
def test_safe_domain_failure_has_no_secret_or_replay(
    service: Service, tmp_path: Path, failure: type[Exception]
) -> None:
    service.failure = failure("private-domain-error")
    result = CliRunner().invoke(
        llm_access.app,
        [
            "issue",
            "--agent-id",
            "agent",
            "--subject",
            "development",
            "--output",
            str(tmp_path / "result"),
        ],
    )
    assert result.exit_code == 1
    assert len(service.calls) == 1
    assert SECRET not in result.output and "private-domain-error" not in result.output


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["inspect", "--supply-id", "supply"],
            {"command": "inspect", "supply_id": "supply"},
        ),
        (
            ["lookup", "--agent-id", "agent", "--subject", "development"],
            {"command": "lookup", "agent_id": "agent", "subject": "development"},
        ),
        (
            ["revoke", "--supply-id", "supply"],
            {"command": "revoke", "supply_id": "supply", "token_id": None},
        ),
        (
            ["revoke", "--supply-id", "supply", "--token-id", "token"],
            {"command": "revoke", "supply_id": "supply", "token_id": "token"},
        ),
    ],
)
def test_nonsecret_management_delegates_exactly(
    service: Service, args: list[str], expected: dict[str, object]
) -> None:
    result = CliRunner().invoke(llm_access.app, args)
    assert result.exit_code == 0, result.output
    assert service.calls == [expected]
    assert SECRET not in result.output


def test_output_write_failure_reports_uncertain_state_without_retry(
    service: Service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_fsync(fd: int) -> None:
        raise OSError("private-filesystem-error")

    monkeypatch.setattr(llm_access.os, "fsync", fail_fsync)
    result = CliRunner().invoke(
        llm_access.app,
        [
            "issue",
            "--agent-id",
            "agent",
            "--subject",
            "development",
            "--output",
            str(tmp_path / "result"),
        ],
    )
    assert result.exit_code == 1
    assert len(service.calls) == 1
    assert "inspect supply state" in result.stderr
    assert (
        SECRET not in result.output and "private-filesystem-error" not in result.output
    )


@pytest.mark.parametrize("subject", ["", "x" * 257])
def test_invalid_identifier_fails_before_output_or_issuance(
    service: Service, tmp_path: Path, subject: str
) -> None:
    output = tmp_path / "credential.json"
    result = CliRunner().invoke(
        llm_access.app,
        [
            "issue",
            "--agent-id",
            "agent",
            "--subject",
            subject,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 2
    assert service.calls == [] and not output.exists()
