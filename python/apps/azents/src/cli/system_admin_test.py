"""System administrator operator CLI tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from azcommon.result import Failure, Result, Success
from typer.testing import CliRunner

from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import (
    SystemUserNotFound,
    SystemUserRoleAssignment,
)
from cli import system_admin


@dataclass
class _Config:
    """Minimal runtime config used by the CLI test."""

    runtime_env: str = "test"
    sentry_dsn: str | None = None


def _load_config() -> _Config:
    """Return the minimal CLI test config."""
    return _Config()


class _Container:
    """Container stub that returns the configured service."""

    def __init__(self, service: "_RoleService") -> None:
        self.service = service

    async def solve(self, _type: type[object]) -> "_RoleService":
        """Return the configured service."""
        return self.service


class _RoleService:
    """Role service stub for CLI adapter tests."""

    def __init__(
        self,
        result: Result[SystemUserRoleAssignment, SystemUserNotFound],
    ) -> None:
        self.result = result
        self.calls: list[tuple[str, SystemUserRole, str]] = []

    async def grant_by_email(
        self,
        email: str,
        role: SystemUserRole,
        *,
        source: str,
    ) -> Result[SystemUserRoleAssignment, SystemUserNotFound]:
        """Record the adapter input and return the configured result."""
        self.calls.append((email, role, source))
        return self.result


def _configure_cli(monkeypatch: pytest.MonkeyPatch, service: _RoleService) -> None:
    """Replace runtime infrastructure with deterministic test doubles."""
    monkeypatch.setattr(system_admin.Config, "from_env", _load_config)
    monkeypatch.setattr(
        system_admin,
        "configure_logging_for_runtime",
        lambda **_kwargs: None,
    )

    @asynccontextmanager
    async def run_with_container(
        _config: _Config,
    ) -> AsyncGenerator[_Container, None]:
        yield _Container(service)

    monkeypatch.setattr(system_admin, "run_with_container", run_with_container)


class TestSystemAdminCLI:
    """System administrator CLI adapter tests."""

    def test_grant_reports_assignment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Grant the role and print only non-secret assignment metadata."""
        assignment = SystemUserRoleAssignment(
            user_id="user-id",
            role=SystemUserRole.SYSTEM_ADMIN,
            granted_by_user_id=None,
            granted_at=datetime.datetime.now(datetime.timezone.utc),
        )
        service = _RoleService(Success(assignment))
        _configure_cli(monkeypatch, service)

        result = CliRunner().invoke(
            system_admin.app,
            ["grant", "--email", " Admin@example.com "],
        )

        assert result.exit_code == 0
        assert "user_id: user-id" in result.stdout
        assert "role: system_admin" in result.stdout
        assert service.calls == [
            (
                " Admin@example.com ",
                SystemUserRole.SYSTEM_ADMIN,
                "operator_cli",
            )
        ]

    def test_grant_rejects_unknown_email(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Return a CLI usage error when no exact email matches."""
        service = _RoleService(
            Failure(SystemUserNotFound(user_id="missing@example.com"))
        )
        _configure_cli(monkeypatch, service)

        result = CliRunner().invoke(
            system_admin.app,
            ["grant", "--email", "missing@example.com"],
        )

        assert result.exit_code == 2
        assert "No existing User matches the exact email." in result.stderr
