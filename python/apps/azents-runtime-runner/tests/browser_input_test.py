"""Confidential input stays in Runtime subprocesses until native field input."""

import base64
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserOpenCommand,
)
from browser_test import (
    _action,
    authority,
    observe,
    target,
)
from nacl.public import PublicKey, SealedBox
from playwright.async_api import Error

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_input import BrowserInputError, BrowserInputKey
from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace

pytest_plugins = ("browser_test",)

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "python/apps/azents/src/azents/resources/vfs/global/skills/browser"
    / "scripts/encrypt.py"
)


def encrypted(key: BrowserInputKey, value: bytes) -> str:
    public = PublicKey(base64.urlsafe_b64decode(key.public_key))
    return base64.urlsafe_b64encode(SealedBox(public).encrypt(value)).decode()


@pytest.mark.parametrize("value", [b"", b"canary", b"x" * 4096, "값" * 1365])
def test_script_and_process_key_round_trip(value: bytes | str) -> None:
    key = BrowserInputKey()
    text = value if isinstance(value, str) else value.decode()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--env", "SYNTHETIC_PASSWORD"],
        env={
            **os.environ,
            "AZENTS_BROWSER_INPUT_PUBLIC_KEY": key.public_key,
            "SYNTHETIC_PASSWORD": text,
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert not result.stderr
    assert len(result.stdout.splitlines()) == 1
    assert key.decrypt(result.stdout.strip()) == text
    if text:
        assert text not in result.stdout


@pytest.mark.parametrize("mutation", ["wrong_key", "corrupt", "oversized", "utf8"])
def test_invalid_input_is_value_free(mutation: str) -> None:
    key = BrowserInputKey()
    ciphertext = encrypted(key, b"synthetic-private-canary")
    if mutation == "wrong_key":
        key = BrowserInputKey()
    elif mutation == "corrupt":
        ciphertext = "!" + ciphertext[1:]
    elif mutation == "oversized":
        ciphertext = encrypted(key, b"x" * 4097)
    elif mutation == "utf8":
        ciphertext = encrypted(key, b"\xff")
    with pytest.raises(BrowserInputError, match="^Browser encrypted input is invalid$"):
        key.decrypt(ciphertext)
    assert "synthetic-private-canary" not in repr(key)


@pytest.mark.parametrize("missing", ["key", "source", "oversized", "invalid_key"])
def test_script_failure_does_not_echo_environment(missing: str) -> None:
    environment = {**os.environ, "SYNTHETIC_PASSWORD": "private-canary" * 400}
    environment["AZENTS_BROWSER_INPUT_PUBLIC_KEY"] = BrowserInputKey().public_key
    if missing == "key":
        environment.pop("AZENTS_BROWSER_INPUT_PUBLIC_KEY")
    elif missing == "source":
        environment.pop("SYNTHETIC_PASSWORD")
    elif missing == "invalid_key":
        environment["AZENTS_BROWSER_INPUT_PUBLIC_KEY"] = "private-key-canary"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--env", "SYNTHETIC_PASSWORD"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "canary" not in result.stderr and "Traceback" not in result.stderr


def test_command_injection_is_last_and_manager_recreation_reuses_key(
    tmp_path: Path,
) -> None:
    key = BrowserInputKey()
    for _ in range(2):
        manager = RunnerBrowserManager(
            workspace_root=tmp_path, proxy=None, input_key=key
        )
        operations = RunnerOperations(
            client=AsyncMock(),
            browser_manager=manager,
            workspace=Workspace(str(tmp_path)),
            execution_backend=DirectExecutionBackend(
                inherited_environment={"AZENTS_BROWSER_INPUT_PUBLIC_KEY": "stale"}
            ),
        )
        spec = operations._command_spec(
            command="true",
            cwd=tmp_path,
            operation_environment={
                "AZENTS_BROWSER_INPUT_PUBLIC_KEY": "caller",
                "SYNTHETIC_PASSWORD": "delegated",
            },
            managed=True,
        )
        assert spec.environment["AZENTS_BROWSER_INPUT_PUBLIC_KEY"] == key.public_key
        assert spec.environment["SYNTHETIC_PASSWORD"] == "delegated"


@pytest.mark.usefixtures("manager", "site")
async def test_native_encrypted_fill_and_value_free_sdk_failure(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    actor = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(actor, None, site, None))
    current = target(opened)
    observed = await observe(manager, actor, current)
    ref = next(item for item in observed.refs if item.tag == "input")
    action = replace(
        _action("fill", ref=ref.id, observation_id=ref.observation_id),
        encrypted_text=encrypted(manager.input_key, b"synthetic-native-canary"),
    )
    result = await manager.execute(BrowserActCommand(actor, current, action))
    assert result.action_state == "dispatched"
    native = manager.tasks[current.task_id].pages[current.page_id].page
    assert await native.locator("input[type=password]").input_value() == (
        "synthetic-native-canary"
    )
    assert "synthetic-native-canary" not in repr(result)
    assert action.text is None
    with monkeypatch.context() as patch:
        decrypt = Mock(
            side_effect=AssertionError("Stale reference must precede decrypt")
        )
        patch.setattr(manager.input_key, "decrypt", decrypt)
        with pytest.raises(BrowserFailure) as stale:
            await manager.execute(
                BrowserActCommand(
                    actor, current, replace(action, observation_id="old-observation")
                )
            )
        assert stale.value.code == "browser_stale_reference"
        decrypt.assert_not_called()
    with pytest.raises(BrowserFailure) as obsolete:
        await manager.execute(
            BrowserActCommand(
                actor,
                current,
                replace(
                    action,
                    encrypted_text=encrypted(BrowserInputKey(), b"obsolete-canary"),
                ),
            )
        )
    assert obsolete.value.code == "browser_encrypted_input_invalid"
    assert await native.locator("input[type=password]").input_value() == (
        "synthetic-native-canary"
    )
    handle = manager._reference(
        manager.tasks[current.task_id].pages[current.page_id],
        native.main_frame,
        action,
    )
    monkeypatch.setattr(
        handle, "fill", AsyncMock(side_effect=Error("synthetic-native-canary"))
    )
    with pytest.raises(BrowserFailure) as failure:
        await manager.execute(BrowserActCommand(actor, current, action))
    assert failure.value.code == "browser_encrypted_input_failed"
    assert "canary" not in str(failure.value)
    assert "synthetic-native-canary" not in caplog.text
