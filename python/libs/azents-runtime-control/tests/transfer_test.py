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
    """Limit data-plane Runner Transfer bytes to bounded chunks."""
    service = runtime_runner_transfer_pb2.DESCRIPTOR.services_by_name[
        "RuntimeRunnerTransfer"
    ]
    assert tuple(method.name for method in service.methods) == (
        "DownloadTransfer",
        "UploadTransfer",
        "ClaimDirectObjectDownload",
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


def test_workspace_upload_schema_is_metadata_only() -> None:
    """Keep Workspace upload coordination metadata-only."""
    service = runtime_transfer_coordinator_pb2.DESCRIPTOR.services_by_name[
        "RuntimeWorkspaceUploadCoordinator"
    ]
    assert tuple(method.name for method in service.methods) == (
        "CreateWorkspaceUpload",
        "IssueWorkspaceUploadTicket",
        "FinalizeWorkspaceUpload",
        "GetWorkspaceUpload",
        "CancelWorkspaceUpload",
        "RetryWorkspaceUpload",
    )

    messages = runtime_transfer_coordinator_pb2.DESCRIPTOR.message_types_by_name
    assert (
        messages["WorkspaceUploadStatus"].fields_by_name["destination_evidence"].number
        == 19
    )


def test_workspace_upload_coordinator_only_carries_opaque_bytes() -> None:
    """Prevent Workspace upload metadata from becoming a storage authority plane."""
    byte_fields = [
        field.full_name
        for message in (
            runtime_transfer_coordinator_pb2.DESCRIPTOR.message_types_by_name.values()
        )
        for field in message.fields
        if field.type is FieldDescriptor.TYPE_BYTES
    ]
    assert byte_fields == [
        "azents.runtime_control.v1.AdmitTransferRequest.conflict_precondition",
        "azents.runtime_control.v1.DestinationEvidence.conflict_precondition",
        "azents.runtime_control.v1.RetryWorkspaceUploadRequest.conflict_precondition",
    ]

    forbidden = ("body", "bucket", "key", "credential")
    for (
        message
    ) in runtime_transfer_coordinator_pb2.DESCRIPTOR.message_types_by_name.values():
        for field in message.fields:
            assert not any(token in field.name.lower() for token in forbidden)


def test_runner_control_transfer_messages_carry_only_metadata() -> None:
    """Allow bounded opaque conflict tokens but reject inline file data."""
    messages = runtime_runner_control_pb2.DESCRIPTOR.message_types_by_name
    opaque_bytes = {
        "azents.runtime_control.v1.RunnerTransferIntent.conflict_precondition",
        "azents.runtime_control.v1.RunnerTransferResult.conflict_precondition",
    }
    for name in (
        "RunnerTransferIntent",
        "RunnerTransferCancel",
        "RunnerTransferResult",
    ):
        for field in messages[name].fields:
            if field.type is FieldDescriptor.TYPE_BYTES:
                assert field.full_name in opaque_bytes
            assert all(
                token not in field.name.lower()
                for token in ("body", "chunk", "bucket", "key", "url", "credential")
            )
