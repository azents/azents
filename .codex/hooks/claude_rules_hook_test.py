from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("claude_rules_hook.py")
SPEC = importlib.util.spec_from_file_location("claude_rules_hook", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {MODULE_PATH}")
hook = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hook
SPEC.loader.exec_module(hook)


class HookInputTest(unittest.TestCase):
    def test_decodes_canonical_fields(self) -> None:
        payload = hook._decode_hook_input(
            {
                "cwd": "/repo",
                "session_id": "session-1",
                "source": "clear",
                "transcript_path": "/tmp/transcript.jsonl",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "README.md",
                    "command": "cat README.md",
                },
                "tool_response": {"success": True},
                "provider_owned": "ignored",
            }
        )

        self.assertEqual(payload.cwd, "/repo")
        self.assertEqual(payload.session_id, "session-1")
        self.assertEqual(payload.source, "clear")
        self.assertEqual(payload.transcript_path, Path("/tmp/transcript.jsonl"))
        self.assertEqual(payload.tool_name, "Write")
        self.assertEqual(payload.tool_input.file_paths, ("README.md",))
        self.assertEqual(payload.tool_input.command, "cat README.md")
        self.assertFalse(payload.tool_failed)

    def test_decodes_supported_aliases(self) -> None:
        payload = hook._decode_hook_input(
            {
                "sessionID": "session-2",
                "transcriptPath": "/tmp/transcript.jsonl",
                "toolName": "Bash",
                "toolInput": {
                    "filePath": "one.md",
                    "path": "two.md",
                    "command": "cat three.md",
                },
            }
        )

        self.assertEqual(payload.session_id, "session-2")
        self.assertEqual(payload.transcript_path, Path("/tmp/transcript.jsonl"))
        self.assertEqual(payload.tool_name, "Bash")
        self.assertEqual(payload.tool_input.file_paths, ("one.md", "two.md"))

    def test_detects_failed_tool_responses(self) -> None:
        responses = (
            {"success": False},
            {"is_error": True},
            {"status": "FAILED"},
            {"error": "boom"},
        )

        for response in responses:
            with self.subTest(response=response):
                payload = hook._decode_hook_input({"tool_output": response})
                self.assertTrue(payload.tool_failed)

    def test_read_hook_input_tolerates_invalid_json(self) -> None:
        with patch.object(sys, "stdin", io.StringIO("{")):
            payload = hook._read_hook_input()

        self.assertEqual(payload, hook._empty_hook_input())


class HookStateTest(unittest.TestCase):
    def test_reads_validated_state_and_writes_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "active_rules": {"one.md": "hash", "invalid.md": 1},
                        "last_transcript_size": 42,
                        "provider_owned": "ignored",
                    }
                ),
                encoding="utf-8",
            )

            state = hook._read_state(path)

            self.assertEqual(state.active_rules, {"one.md": "hash"})
            self.assertEqual(state.last_transcript_size, 42)

            hook._write_state(path, state)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "active_rules": {"one.md": "hash"},
                    "last_transcript_size": 42,
                },
            )

    def test_preserves_legacy_active_rule_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "active_rule_realpaths": ["one.md", 2],
                        "last_transcript_size": "invalid",
                    }
                ),
                encoding="utf-8",
            )

            state = hook._read_state(path)

        self.assertEqual(state.active_rules, {"one.md": ""})
        self.assertIsNone(state.last_transcript_size)


class TargetExtractionTest(unittest.TestCase):
    def test_extracts_typed_file_and_bash_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            payload = hook._decode_hook_input(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "path": "one.md",
                        "command": "cat two.md",
                    },
                }
            )

            targets = hook._targets_from_payload(payload, project_root)

        self.assertEqual(
            targets,
            [
                project_root / "one.md",
                project_root / "two.md",
            ],
        )


if __name__ == "__main__":
    unittest.main()
