"""Tests for the agent-basic fixture provider."""

import datetime as dt
import json
from pathlib import Path

import pytest

from testenv.fixture_agent_basic import AgentBasicFixtureProvider
from testenv.fixture_manifest import (
    FIXTURE_SCHEMA_VERSION,
    FixtureManifest,
    WorktreeFingerprint,
    load_fixture_manifest,
    save_fixture_manifest,
)
from testenv.fixture_paths import fixture_private_state_path
from testenv.fixture_resources import FixtureCommandResult, FixtureContext
from testenv.types import SetupOutcome, SetupSpec


class _FakeDevserverProvider:
    """Test provider that returns a fixed devserver dependency result."""

    id = "devserver"

    def __init__(self, result: FixtureCommandResult) -> None:
        self._result = result

    def up(self, ctx: FixtureContext) -> FixtureCommandResult:
        del ctx
        return self._result

    def doctor(self, ctx: FixtureContext) -> FixtureCommandResult:
        del ctx
        return self._result

    def reset(self, ctx: FixtureContext) -> FixtureCommandResult:
        del ctx
        return self._result


def _ctx(testenv_root: Path) -> FixtureContext:
    """Create a fixed fixture context for tests."""
    return FixtureContext(
        testenv_root=testenv_root,
        now=dt.datetime(2026, 5, 12, 9, 5, tzinfo=dt.UTC),
    )


def _current_worktree(
    testenv_root: Path,
    *,
    fingerprint: str = "sha256:current",
) -> WorktreeFingerprint:
    """Create a current worktree fingerprint for tests."""
    return WorktreeFingerprint(
        repo_root=str(testenv_root.parent.parent),
        head_sha="abcdef1",
        dirty_hash="sha256:dirty",
        env_hash="sha256:env",
        fingerprint=fingerprint,
    )


def _devserver_manifest(testenv_root: Path) -> FixtureManifest:
    """Create a devserver manifest for agent-basic tests."""
    now = dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC)
    return FixtureManifest(
        schema_version=FIXTURE_SCHEMA_VERSION,
        fixture_id="devserver",
        status="ready",
        created_at=now,
        updated_at=now,
        worktree=_current_worktree(testenv_root),
        resources={
            "devserver": {
                "session_name": "azents-testenv-devserver",
                "public_url": "http://localhost:8010",
                "admin_url": "http://localhost:8011",
            }
        },
        provides={
            "devserver.public_url": "http://localhost:8010",
            "devserver.admin_url": "http://localhost:8011",
            "devserver.session_name": "azents-testenv-devserver",
        },
        doctor=None,
    )


def _ready_dependency_result(testenv_root: Path) -> FixtureCommandResult:
    """Create a ready devserver dependency result."""
    return FixtureCommandResult(
        fixture_id="devserver",
        status="ready",
        checks=(),
        manifest=_devserver_manifest(testenv_root),
        message="Fixture devserver is ready",
        guidance=None,
    )


def _setup_spec(setup_id: str) -> SetupSpec:
    """Create a SetupSpec for tests."""
    return SetupSpec(
        id=setup_id,
        handler=Path(f"/tmp/{setup_id}.py"),
        requires=[],
        provides=[],
        idempotent=True,
        verify=None,
        reclaim=None,
        teardown=None,
        scope="run",
        locks=[],
        markdown_path=Path(f"/tmp/{setup_id}.md"),
    )


def _seed_private_state(path: Path) -> None:
    """Write private state JSON that mimics a setup handler result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_meta": {
                    "run_id": "fixture-agent-basic",
                    "started_at": "2026-05-12T09:00:00+00:00",
                },
                "run": {
                    "user": {
                        "email": "qa@example.com",
                        "access_token": "sk-private-access",
                        "refresh_token": "sk-private-refresh",
                    },
                    "ws": {"handle": "qa-workspace", "name": "QA Workspace"},
                    "integration": {
                        "id": "int_123",
                        "provider": "openai",
                        "name": "dummy-openai",
                        "api_key": "sk-hidden",
                    },
                    "runtime_setting": {"id": "shell_123"},
                    "agent": {"id": "agent_123", "model_slug": "gpt-4o-mini"},
                    "fixture": {
                        "worktree_fingerprint": "sha256:current",
                        "repo_root": str(path.parent.parent.parent),
                        "head_sha": "abcdef1",
                    },
                },
                "tc": {},
                "_finalizers": [],
                "_verified_at": {
                    "user.email": "2026-05-12T09:00:00+00:00",
                    "ws.handle": "2026-05-12T09:00:00+00:00",
                    "ws.name": "2026-05-12T09:00:00+00:00",
                    "integration.id": "2026-05-12T09:00:00+00:00",
                    "integration.provider": "2026-05-12T09:00:00+00:00",
                    "integration.name": "2026-05-12T09:00:00+00:00",
                    "runtime_setting.id": "2026-05-12T09:00:00+00:00",
                    "agent.id": "2026-05-12T09:00:00+00:00",
                    "agent.model_slug": "2026-05-12T09:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )


def test_fixture_up_agent_basic_saves_sanitized_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """up saves a public manifest without leaking private state secrets."""
    provider = AgentBasicFixtureProvider(_FakeDevserverProvider(_ready_dependency_result(tmp_path)))
    state_path = fixture_private_state_path("agent-basic", tmp_path)
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.load_all_setups",
        lambda _: {
            sid: _setup_spec(sid)
            for sid in (
                "test-user-workspace",
                "llm-provider-dummy",
                "",
                "agent-dummy-key",
            )
        },
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.resolve_setup_dag",
        lambda wanted, all_setups: [all_setups[sid] for sid in wanted],
    )

    def fake_run_setup(spec: SetupSpec, state: object, config: object = None) -> SetupOutcome:
        del spec, state, config
        _seed_private_state(state_path)
        return SetupOutcome(setup_id="seed", outcome="ran", reason="executed")

    monkeypatch.setattr("testenv.fixture_agent_basic.run_setup", fake_run_setup)
    result = provider.up(_ctx(tmp_path))

    assert result.status == "ready"
    assert state_path.exists() is True
    manifest = load_fixture_manifest("agent-basic", tmp_path)
    assert manifest.resources["user"] == {"email": "qa@example.com"}
    assert manifest.resources["workspace"] == {
        "handle": "qa-workspace",
        "name": "QA Workspace",
    }
    assert manifest.resources["agent"] == {"id": "agent_123", "model_slug": "gpt-4o-mini"}
    assert manifest.provides["devserver.public_url"] == "http://localhost:8010"
    raw_manifest = (tmp_path / ".state" / "fixtures" / "agent-basic.json").read_text(
        encoding="utf-8"
    )
    assert "access_token" not in raw_manifest
    assert "refresh_token" not in raw_manifest
    assert "api_key" not in raw_manifest
    assert "sk-private-access" not in raw_manifest
    assert "sk-hidden" not in raw_manifest


def test_fixture_up_agent_basic_requires_ready_devserver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The setup chain does not run unless devserver is ready."""
    provider = AgentBasicFixtureProvider(
        _FakeDevserverProvider(
            FixtureCommandResult(
                fixture_id="devserver",
                status="stale",
                checks=(),
                manifest=None,
                message="Fixture devserver is stale",
                guidance="Run `uv run testenv fixture up devserver`.",
                error_code="FIXTURE_MANIFEST_NOT_READY",
            )
        )
    )
    monkeypatch.setattr(
        provider,
        "_run_setup_chain",
        lambda ctx, state: pytest.fail("setup chain must not run when devserver is not ready"),
    )

    result = provider.up(_ctx(tmp_path))

    assert result.status == "stale"
    assert result.error_code == "FIXTURE_AGENT_BASIC_DEVSERVER_NOT_READY"


def test_fixture_doctor_reports_missing_private_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """doctor reports stale when manifest exists but private state is missing."""
    provider = AgentBasicFixtureProvider(_FakeDevserverProvider(_ready_dependency_result(tmp_path)))
    manifest = FixtureManifest(
        schema_version=FIXTURE_SCHEMA_VERSION,
        fixture_id="agent-basic",
        status="ready",
        created_at=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC),
        worktree=_current_worktree(tmp_path),
        resources={"devserver": _devserver_manifest(tmp_path).resources["devserver"]},
        provides={"user.email": "qa@example.com"},
        doctor=None,
    )
    save_fixture_manifest(manifest, tmp_path)
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    result = provider.doctor(_ctx(tmp_path))

    assert result.status == "stale"
    assert result.error_code == "FIXTURE_AGENT_BASIC_STATE_MISSING"


def test_fixture_doctor_reports_incomplete_private_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """doctor reports incomplete when required ids are missing from private state."""
    provider = AgentBasicFixtureProvider(_FakeDevserverProvider(_ready_dependency_result(tmp_path)))
    save_fixture_manifest(
        FixtureManifest(
            schema_version=FIXTURE_SCHEMA_VERSION,
            fixture_id="agent-basic",
            status="ready",
            created_at=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC),
            updated_at=dt.datetime(2026, 5, 12, 9, 0, tzinfo=dt.UTC),
            worktree=_current_worktree(tmp_path),
            resources={"devserver": _devserver_manifest(tmp_path).resources["devserver"]},
            provides={"user.email": "qa@example.com"},
            doctor=None,
        ),
        tmp_path,
    )
    state_path = fixture_private_state_path("agent-basic", tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "_meta": {
                    "run_id": "fixture-agent-basic",
                    "started_at": "2026-05-12T09:00:00+00:00",
                },
                "run": {
                    "user": {"email": "qa@example.com"},
                    "fixture": {
                        "worktree_fingerprint": "sha256:current",
                        "repo_root": str(tmp_path.parent.parent),
                        "head_sha": "abcdef1",
                    },
                },
                "tc": {},
                "_finalizers": [],
                "_verified_at": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    result = provider.doctor(_ctx(tmp_path))

    assert result.status == "stale"
    assert result.error_code == "FIXTURE_AGENT_BASIC_STATE_INCOMPLETE"


def test_fixture_reset_deletes_manifest_and_private_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """reset deletes both public manifest and private state."""
    provider = AgentBasicFixtureProvider(_FakeDevserverProvider(_ready_dependency_result(tmp_path)))
    state_path = fixture_private_state_path("agent-basic", tmp_path)
    _seed_private_state(state_path)
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.current_worktree_fingerprint",
        lambda _: _current_worktree(tmp_path),
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.load_all_setups",
        lambda _: {
            sid: _setup_spec(sid)
            for sid in (
                "test-user-workspace",
                "llm-provider-dummy",
                "",
                "agent-dummy-key",
            )
        },
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.resolve_setup_dag",
        lambda wanted, all_setups: [all_setups[sid] for sid in wanted],
    )
    monkeypatch.setattr(
        "testenv.fixture_agent_basic.run_setup",
        lambda spec, state, config=None: SetupOutcome(
            setup_id=spec.id,
            outcome="skipped",
            reason="ok",
        ),
    )
    provider.up(_ctx(tmp_path))

    result = provider.reset(_ctx(tmp_path))

    assert result.status == "ready"
    assert (tmp_path / ".state" / "fixtures" / "agent-basic.json").exists() is False
    assert state_path.exists() is False
