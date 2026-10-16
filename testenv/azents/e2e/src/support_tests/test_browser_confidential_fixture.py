"""Confidential fixture consumes actual returned paths, process output and refs."""

import base64
import json

import pytest

from support import browser_confidential_fixture as fixture
from support import image_generation_openai_proxy as proxy


def test_proxy_does_not_decode_assistant_call_as_a_tool_result() -> None:
    item = proxy._decode_model_input_item(
        {
            "type": "function_call",
            "call_id": fixture.PREFIX + "import",
            "name": "import_file",
            "arguments": "{}",
        }
    )
    assert item.confidential_output is None


def observation(stage: str, output: object) -> fixture.Observation:
    value = fixture.decode_output(fixture.PREFIX + stage, output)
    assert value is not None
    return value


def _targets() -> list[fixture.Observation]:
    page = {"task_id": "t", "id": "p", "resource_incarnation": "i", "title": "ready"}
    return [
        observation("open", json.dumps({"page": page, "refs": []})),
        observation(
            "observe",
            [
                {
                    "type": "input_text",
                    "text": json.dumps(
                        {
                            "page": page,
                            "refs": [
                                {
                                    "id": "r",
                                    "observation_id": "o",
                                    "label": "Confidential password",
                                },
                                {
                                    "id": "a",
                                    "observation_id": "o",
                                    "label": "Confidential account",
                                },
                            ],
                        }
                    ),
                }
            ],
        ),
    ]


def test_fixture_import_process_poll_and_encrypted_fill_use_actual_results() -> None:
    observations = [observation("skill", "Browser Skill loaded")]
    call = fixture.next_call(observations)
    assert call is not None and call.name == "import_file"
    observations.append(
        observation(
            "import",
            "Imported azents://skills/azents/browser/scripts/encrypt.py "
            "to /tmp/actual copy.py (vfs, text/x-python, 100 bytes).",
        )
    )
    call = fixture.next_call(observations)
    assert call is not None and call.name == "browser_open"
    observations.extend(_targets())
    call = fixture.next_call(observations)
    assert call is not None and call.name == "exec_command"
    assert "'/tmp/actual copy.py'" in str(call.arguments["command"])
    ciphertext = base64.urlsafe_b64encode(b"x" * 96).decode()
    observations.append(
        observation(
            "encrypt",
            "status: running\n\nprocess_id: actual-process\n\n"
            f"stdout:\n{ciphertext[:40]}",
        )
    )
    call = fixture.next_call(observations)
    assert call is not None and call.name == "write_stdin"
    assert call.arguments["process_id"] == "actual-process"
    observations.append(
        observation(
            "poll1",
            "status: exited_unread\n\nprocess_id: actual-process\n\n"
            f"exit_code: 0\n\nstdout:\n{ciphertext[40:]}\n\n"
            "stderr:\nInstalled packages",
        )
    )
    call = fixture.next_call(observations)
    assert call is not None and call.name == "browser_act"
    assert call.arguments["encrypted_text"] == ciphertext
    assert call.arguments["ref"] == "r" and call.arguments["observation_id"] == "o"
    assert "text" not in call.arguments


def test_fixture_does_not_accept_nonzero_encryption_exit() -> None:
    with pytest.raises(ValueError, match="process failed"):
        observation(
            "encrypt",
            "status: exited_unread\n\nprocess_id: p\n\nexit_code: 1\n\n"
            "stderr:\nSource environment variable is unavailable",
        )


def test_replacement_observations_are_separate_and_require_old_key_rejection() -> None:
    initial = observation(
        "verify",
        json.dumps(
            {
                "page": {
                    "task_id": "old",
                    "id": "old",
                    "resource_incarnation": "old",
                    "title": "Confidential input verified",
                },
                "refs": [],
            }
        ),
    )
    call = fixture.next_call([initial], old_ciphertext="A" * 64)
    assert call is not None and call.stage == "skill"
    rejected = fixture.decode_output(
        fixture.REPLACEMENT_PREFIX + "oldfill", "Browser encrypted input is invalid"
    )
    assert rejected is not None and rejected.rejected and rejected.replacement
    with pytest.raises(ValueError, match="not rejected"):
        fixture.decode_output(fixture.REPLACEMENT_PREFIX + "oldfill", "dispatched")
