"""Routine attachments reuse existing file authority and transfer boundaries."""

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success

from azents.core.exchange_file_errors import FileAccessDenied
from azents.engine.tools.present_file_test import (
    _TARGET,
    _authority,
    _make_exchange_file,
)
from azents.engine.tools.runtime_instruction_context import RuntimeInstructionContext
from azents.engine.tools.testing import FakeSharedStorage
from azents.services.exchange_file import (
    ExchangeFileService,
    ExchangeFileTransferSource,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
)
from azents.services.routine.files import RoutineFileService


@dataclass(frozen=True)
class Subject:
    service: RoutineFileService
    transfers: AsyncMock
    exchange: AsyncMock


def subject() -> Subject:
    transfers = AsyncMock(spec=ExternalChannelFileTransferService)
    exchange = AsyncMock(spec=ExchangeFileService)
    transfers.exchange_file_service = exchange
    return Subject(
        service=RoutineFileService(transfers=transfers),
        transfers=transfers,
        exchange=exchange,
    )


async def test_channel_files_use_authorized_existing_transfer() -> None:
    f = subject()
    f.transfers.prepare_outbound.return_value = ()
    file = _make_exchange_file(filename="report.txt", size_bytes=5)
    f.exchange.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=file)
    )
    result = await f.service.prepare(
        paths=[file.uri],
        binding_id="binding",
        execution_id="execution",
        authority=_authority(),
        runtime=None,
    )
    assert result.binding_id == "binding" and result.attachments == ()
    f.transfers.prepare_outbound.assert_awaited_once_with(
        session_id=_authority().session_id,
        agent_id=_authority().agent_id,
        binding_id="binding",
        paths=[file.uri],
        file_storage=None,
        authority=_authority(),
    )


async def test_session_exchange_file_keeps_authorized_attachment_metadata() -> None:
    f = subject()
    file = _make_exchange_file(filename="report.txt", size_bytes=5)
    f.exchange.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=file)
    )
    result = await f.service.prepare(
        paths=[file.uri],
        binding_id=None,
        execution_id="execution",
        authority=_authority(),
        runtime=None,
    )
    assert result.manifests == ()
    assert result.attachments[0].uri == file.uri
    assert result.attachments[0].name == "report.txt"
    f.exchange.resolve_transfer_source_for_authority.assert_awaited_once_with(
        uri=file.uri, authority=_authority()
    )


async def test_session_denied_exchange_file_fails_closed() -> None:
    f = subject()
    f.exchange.resolve_transfer_source_for_authority.return_value = Failure(
        FileAccessDenied()
    )
    with pytest.raises(ValueError, match="access is denied"):
        await f.service.prepare(
            paths=["exchange://foreign"],
            binding_id=None,
            execution_id="execution",
            authority=_authority(),
            runtime=None,
        )


@pytest.mark.parametrize(
    "path", ["relative.txt", "https://example.com/file", "artifact://file"]
)
async def test_invalid_sources_are_not_read(path: str) -> None:
    with pytest.raises(ValueError, match="absolute Runtime"):
        await subject().service.prepare(
            paths=[path],
            binding_id=None,
            execution_id="execution",
            authority=_authority(),
            runtime=None,
        )


@pytest.mark.parametrize("binding_id", [None, "binding"])
async def test_failed_preparation_retry_can_publish_changed_file(
    binding_id: str | None,
) -> None:
    f = subject()
    f.transfers.prepare_outbound.return_value = ()
    publish = AsyncMock()
    file = _make_exchange_file(filename="report.txt", size_bytes=5)
    publish.publish.return_value = file
    target = AsyncMock(return_value=_TARGET)
    storage = FakeSharedStorage({"/tmp/report.txt": b"hello"})
    runtime = RuntimeInstructionContext(
        file_storage=storage,
        workspace_root=None,
        projects=(),
        transfer_service=AsyncMock(),
        publication_service=publish,
        provider_delivery_service=AsyncMock(),
        resolve_runtime_target=target,
    )
    with pytest.raises(ValueError, match="not found"):
        await f.service.prepare(
            paths=["/tmp/report.txt", "/tmp/missing.txt"],
            binding_id=binding_id,
            execution_id="execution",
            authority=_authority(),
            runtime=runtime,
        )
    request = publish.publish.call_args.args[0]
    assert request.runtime_path == "/tmp/report.txt" and request.expected_size == 5
    assert request.authority == _authority() and request.target == _TARGET
    storage.add_file("/tmp/report.txt", b"changed bytes")
    storage.add_file("/tmp/missing.txt", b"fixed")
    second = await f.service.prepare(
        paths=["/tmp/report.txt", "/tmp/missing.txt"],
        binding_id=binding_id,
        execution_id="execution",
        authority=_authority(),
        runtime=runtime,
    )
    retried = publish.publish.call_args_list[1].args[0]
    assert retried.expected_size == len(b"changed bytes")
    assert retried.publication_id != request.publication_id
    if binding_id is None:
        assert len(second.attachments) == 2
        f.transfers.prepare_outbound.assert_not_awaited()
    else:
        assert second.attachments == ()
        f.transfers.prepare_outbound.assert_awaited_once_with(
            session_id=_authority().session_id,
            agent_id=_authority().agent_id,
            binding_id=binding_id,
            paths=[file.uri, file.uri],
            file_storage=None,
            authority=_authority(),
        )
