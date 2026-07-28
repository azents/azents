"""Runtime File Transfer protocol schema tests."""

from google.protobuf.descriptor import FieldDescriptor

from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_transfer_pb2,
    runtime_transfer_coordinator_pb2,
)
from azents_runtime_control.transfer import (
    MAX_TRANSFER_CHUNK_BYTES,
    MULTIPART_PART_BYTES,
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
    RUNTIME_TRANSFER_COORDINATOR_AUDIENCE,
)


def test_transfer_protocol_constants_are_exact() -> None:
    """Keep every cross-process fixed protocol constant in one shared module."""
    assert RUNNER_TRANSFER_PROTOCOL_VERSION == "2026-07-25"
    assert RUNNER_TRANSFER_CAPABILITY == "file.transfer.v1"
    assert RUNTIME_TRANSFER_COORDINATOR_AUDIENCE == (
        "azents-runtime-transfer-coordinator"
    )
    assert MAX_TRANSFER_CHUNK_BYTES == 256 * 1024
    assert MULTIPART_PART_BYTES == 5 * 1024 * 1024


def test_runner_transfer_schema_is_directional_and_bounded() -> None:
    """Ensure byte data exists only in the dedicated TransferChunk message."""
    service = runtime_runner_transfer_pb2.DESCRIPTOR.services_by_name[
        "RuntimeRunnerTransfer"
    ]
    assert tuple(method.name for method in service.methods) == (
        "DownloadTransfer",
        "UploadTransfer",
    )
    bytes_fields = [
        field.full_name
        for message in (
            runtime_runner_transfer_pb2.DESCRIPTOR.message_types_by_name.values()
        )
        for field in message.fields
        if field.type is FieldDescriptor.TYPE_BYTES
    ]
    assert bytes_fields == [
        "azents.runtime_control.v1.TransferChunk.data",
    ]


def test_coordinator_schema_carries_no_file_or_storage_authority() -> None:
    """Prevent coordinator drift into a file-body or S3 authority plane."""
    forbidden = ("body", "chunk", "bucket", "key", "url", "credential", "bytes")
    for (
        message
    ) in runtime_transfer_coordinator_pb2.DESCRIPTOR.message_types_by_name.values():
        for field in message.fields:
            assert field.type is not FieldDescriptor.TYPE_BYTES
            assert not any(token in field.name.lower() for token in forbidden)


def test_runner_control_transfer_messages_carry_only_metadata() -> None:
    """Prevent transfer correlation from reintroducing inline file data."""
    messages = runtime_runner_control_pb2.DESCRIPTOR.message_types_by_name
    for name in (
        "RunnerTransferIntent",
        "RunnerTransferCancel",
        "RunnerTransferResult",
    ):
        for field in messages[name].fields:
            assert field.type is not FieldDescriptor.TYPE_BYTES
            assert all(
                token not in field.name.lower()
                for token in ("body", "chunk", "bucket", "key", "url", "credential")
            )
