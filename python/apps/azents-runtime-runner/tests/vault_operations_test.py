"""Confidential Vault operations through the actual local Runner backend."""

import base64
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

from azents_runtime_control.runner import (
    JsonValue,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)
from azents_runtime_control.vault_contract import (
    MAX_VAULT_FILE_BYTES,
    VAULT_FILE_READ,
    VAULT_PROCESS_START,
    VaultOperationContext,
    decode_vault_body,
    encode_vault_body,
)
from nacl.public import PrivateKey, PublicKey, SealedBox

from azents_runtime_runner.execution import DirectExecutionBackend
from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.vault_transport import VaultRecipient
from azents_runtime_runner.workspace import Workspace

_MARKER = b"synthetic-unique-vault-value"


class _Sink:
    def __init__(self) -> None:
        self.events: list[RunnerOperationEvent] = []

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        self.events.append(event)


def _operation(
    kind: str, request_id: str, deadline: datetime, payload: dict[str, JsonValue]
) -> RunnerOperationEnvelope:
    return RunnerOperationEnvelope(
        request_id=request_id,
        runtime_id="runtime",
        runner_generation=3,
        operation_type=kind,
        payload=payload,
        reply_stream_id="reply",
        body_stream_id=None,
        body_chunks=(),
        deadline_at=deadline,
        owner_session_id="session",
    )


async def test_cli_requires_matching_envelope_and_does_not_inherit_value(
    tmp_path: Path,
) -> None:
    sink = _Sink()
    recipient = VaultRecipient()
    key = PublicKey(base64.urlsafe_b64decode(recipient.public_key))
    runner = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        browser_manager=None,
        execution_backend=DirectExecutionBackend(),
        vault_recipient=recipient,
    )
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    context = VaultOperationContext(
        VAULT_PROCESS_START, "runtime", 3, "session", "start", deadline
    )
    cipher = base64.urlsafe_b64encode(
        SealedBox(key).encrypt(
            encode_vault_body(context, b'{"VAULT_FIXTURE_NONCE":"' + _MARKER + b'"}')
        )
    ).decode()
    request = _operation(
        VAULT_PROCESS_START,
        "start",
        deadline,
        {
            "command": 'test -n "$VAULT_FIXTURE_NONCE"',
            "sealed_environment": cipher,
            "yield_time_ms": 1000,
        },
    )
    try:
        await runner.handle(dataclasses.replace(request, request_id="another"))
        assert sink.events[-1].event_type is RuntimeRunnerEventType.FINAL_ERROR
        await runner.handle(request)
        assert sink.events[-1].event_type is RuntimeRunnerEventType.FINAL_SUCCESS
        assert sink.events[-1].payload["exit_code"] == 0
        await runner.handle(
            _operation(
                "process.start",
                "ordinary",
                deadline,
                {
                    "command": 'test -z "${VAULT_FIXTURE_NONCE+x}"',
                    "yield_time_ms": 1000,
                },
            )
        )
        assert sink.events[-1].payload["exit_code"] == 0
        assert _MARKER.decode() not in repr((request, sink.events))
    finally:
        await runner.close()


async def test_file_returns_only_complete_ciphertext(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(_MARKER)
    sink = _Sink()
    audience = PrivateKey.generate()
    runner = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        browser_manager=None,
        execution_backend=DirectExecutionBackend(),
    )
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    request = _operation(
        VAULT_FILE_READ,
        "read",
        deadline,
        {
            "path": str(source),
            "recipient_public_key": base64.urlsafe_b64encode(
                bytes(audience.public_key)
            ).decode(),
        },
    )
    try:
        await runner.handle(request)
        final = sink.events[-1]
        assert final.event_type is RuntimeRunnerEventType.FINAL_SUCCESS
        assert set(final.payload) == {"sealed_value"}
        sealed = final.payload["sealed_value"]
        assert isinstance(sealed, str)
        body = SealedBox(audience).decrypt(base64.urlsafe_b64decode(sealed))
        context = VaultOperationContext(
            VAULT_FILE_READ, "runtime", 3, "session", "read", deadline
        )
        assert decode_vault_body(context, body) == _MARKER
        assert _MARKER.decode() not in repr(sink.events)
        assert source.read_bytes() == _MARKER
        source.write_bytes(b"x" * (MAX_VAULT_FILE_BYTES + 1))
        await runner.handle(dataclasses.replace(request, request_id="too-large"))
        assert sink.events[-1].event_type is RuntimeRunnerEventType.FINAL_ERROR
        assert "sealed_value" not in sink.events[-1].payload
    finally:
        await runner.close()
