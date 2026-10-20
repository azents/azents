"""Native waits and immutable external-target replay for each cleanup owner."""

import asyncio
import datetime
from unittest.mock import AsyncMock, Mock, call

import pytest
from azcommon.infra.s3.service import S3Service

from azents.core.agent_deletion import (
    AgentAvatarDeletionEvidence,
    AgentDeletionOwnershipLost,
    AgentDeletionWaitReason,
)
from azents.core.config import Config, WorkspaceS3Config
from azents.core.enums import AgentDecommissionStatus, AgentSessionStatus
from azents.core.retirement_data import RetirementBlob, RetirementRoot, RootRetirement
from azents.core.upload_images import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)
from azents.repos.agent_decommission_operations import (
    AgentDecommissionOperationsRepository,
)
from azents.repos.agent_deletion_fence import deletion_context
from azents.services.agent_decommission_test import _job
from azents.services.agent_deletion import (
    AgentDeletionExecution,
    AvatarDeletionParticipant,
    ChannelDeletionParticipant,
    DatabaseDeletionParticipant,
    FileDeletionParticipant,
    RuntimeDeletionParticipant,
    SessionRetirementParticipant,
)
from azents.services.uploads.handlers.avatar import AvatarUploadHandler

_NOW = datetime.datetime(2026, 10, 20, tzinfo=datetime.UTC)


def _execution() -> AgentDeletionExecution:
    return AgentDeletionExecution(
        _job(job_id="participant"), "owner", None, None, False
    )


def _config() -> Mock:
    config = Mock(spec=Config)
    config.workspace_s3 = Mock(spec=WorkspaceS3Config, bucket="workspace-test")
    return config


def _avatar() -> StoredImage:
    large = StoredImageFile(
        key="avatar/large", content_type="image/webp", size_bytes=42
    )
    small = StoredImageFile(
        key="avatar/small", content_type="image/webp", size_bytes=12
    )
    return StoredImage(
        filename="avatar.webp",
        default=large,
        original=None,
        thumbnails=StoredImageThumbnails(small=small, medium=None, large=large),
        uploaded_at=_NOW,
    )


@pytest.mark.parametrize("state", ["absent", "archived", "active", "stopping"])
async def test_sessions_keep_native_retirement_and_waits(state: str) -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.list_roots.return_value = (
        ()
        if state == "absent"
        else (
            RetirementRoot(
                id="root",
                status=AgentSessionStatus.ARCHIVED
                if state == "archived"
                else AgentSessionStatus.ACTIVE,
                product_mode=None,
            ),
        )
    )
    operations.retire_root_tree.return_value = RootRetirement(
        retired=state != "stopping",
        archived=state == "active",
        stop_session_ids=("root",) if state == "stopping" else (),
        cleanup_plans=(),
    )
    broker = Mock(send_message=AsyncMock())
    channels = Mock(consume_archive_cleanup=AsyncMock())
    execution = _execution()
    await SessionRetirementParticipant(operations, broker, channels).run(execution)
    expected_wait = {
        "absent": None,
        "archived": AgentDeletionWaitReason.RETENTION,
        "active": AgentDeletionWaitReason.RETENTION,
        "stopping": AgentDeletionWaitReason.ACTIVE_WORK,
    }
    assert execution.wait_reason is expected_wait[state]
    assert not execution.completed
    if state in ("absent", "archived"):
        operations.retire_root_tree.assert_not_awaited()
    else:
        operations.retire_root_tree.assert_awaited_once_with(
            job=execution.job, lease_owner="owner", root_session_id="root"
        )
    assert broker.send_message.await_count == int(state == "stopping")
    assert channels.consume_archive_cleanup.await_count == int(state == "active")
    if state == "absent":
        assert (
            operations.advance_status.await_args.kwargs["status"]
            is AgentDecommissionStatus.FINALIZING
        )
    elif state != "stopping":
        assert (
            operations.advance_status.await_args.kwargs["status"]
            is AgentDecommissionStatus.WAITING_RETENTION
        )
    operations.finalize.assert_not_awaited()


@pytest.mark.parametrize("bound", [False, True])
async def test_runtime_request_uses_owned_binding(bound: bool) -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.runtime_bound.return_value = bound
    runtime = Mock(request_terminal_delete_for_agent=AsyncMock())
    execution = _execution()
    await RuntimeDeletionParticipant(operations, runtime).run(execution)
    if bound:
        operations.require_owned.assert_awaited_once_with(
            job=execution.job, lease_owner="owner"
        )
        runtime.request_terminal_delete_for_agent.assert_awaited_once_with(
            execution.job.agent_id
        )
    else:
        operations.require_owned.assert_not_awaited()
        runtime.request_terminal_delete_for_agent.assert_not_awaited()
    assert not execution.completed


async def test_stale_runtime_attempt_never_dispatches_provider_work() -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.runtime_bound.return_value = True
    operations.require_owned.side_effect = AgentDeletionOwnershipLost("reclaimed")
    runtime = Mock(request_terminal_delete_for_agent=AsyncMock())
    with pytest.raises(AgentDeletionOwnershipLost):
        await RuntimeDeletionParticipant(operations, runtime).run(_execution())
    runtime.request_terminal_delete_for_agent.assert_not_awaited()


async def test_channel_effects_follow_committed_canonical_cleanup() -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    plans = ()
    operations.cleanup_channels.return_value = plans
    channels = Mock(consume_archive_cleanup=AsyncMock(return_value=0))
    execution = _execution()
    await ChannelDeletionParticipant(operations, channels).run(execution)
    channels.consume_archive_cleanup.assert_awaited_once_with(plans)
    operations.cleanup_channels.side_effect = AgentDeletionOwnershipLost("reclaimed")
    channels.consume_archive_cleanup.reset_mock()
    with pytest.raises(AgentDeletionOwnershipLost):
        await ChannelDeletionParticipant(operations, channels).run(execution)
    channels.consume_archive_cleanup.assert_not_awaited()


@pytest.mark.parametrize("failure", ["storage", "receipt", "cancel"])
async def test_file_replay_requires_persisted_blob_success(failure: str) -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    target = RetirementBlob(
        id="file", object_key="immutable/file", blob_deleted_at=None
    )
    operations.prepare_files.return_value = (target,)
    storage = Mock(spec=S3Service)
    error = asyncio.CancelledError() if failure == "cancel" else OSError("unavailable")
    if failure == "receipt":
        operations.mark_blob_deleted.side_effect = [error, None]
    else:
        storage.delete.side_effect = [error, None]
    participant = FileDeletionParticipant(operations, storage, _config())
    execution = _execution()
    with pytest.raises(type(error)) as caught:
        await participant.run(execution)
    assert caught.value is error
    operations.finish_files.assert_not_awaited()
    await participant.run(execution)
    assert (
        storage.delete.await_args_list
        == [call(bucket="workspace-test", key=target.object_key)] * 2
    )
    operations.mark_blob_deleted.assert_awaited_with(
        job=execution.job,
        lease_owner="owner",
        file_id=target.id,
        object_key=target.object_key,
    )
    operations.finish_files.assert_awaited_once_with(
        job=execution.job, lease_owner="owner"
    )
    operations.prepare_files.return_value = (
        RetirementBlob(
            id=target.id, object_key=target.object_key, blob_deleted_at=_NOW
        ),
    )
    storage.delete.reset_mock()
    operations.mark_blob_deleted.reset_mock()
    await participant.run(execution)
    storage.delete.assert_not_awaited()
    operations.mark_blob_deleted.assert_not_awaited()


@pytest.mark.parametrize("present", [False, True])
async def test_avatar_evidence_covers_exact_deduplicated_keys(present: bool) -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.read_avatar.return_value = _avatar() if present else None
    storage = Mock(spec=S3Service)
    execution = _execution()
    await AvatarDeletionParticipant(
        operations, AvatarUploadHandler(), storage, _config()
    ).run(execution)
    assert execution.avatar_evidence == AgentAvatarDeletionEvidence(
        deletion_context(execution.job, lease_owner="owner"),
        ("avatar/large", "avatar/small") if present else (),
    )
    assert {item.kwargs["key"] for item in storage.delete.await_args_list} == (
        {"avatar/large", "avatar/small"} if present else set()
    )
    assert storage.delete.await_count == (2 if present else 0)


async def test_partial_avatar_failure_produces_no_evidence_and_replays_targets() -> (
    None
):
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.read_avatar.return_value = _avatar()
    storage = Mock(spec=S3Service)
    storage.delete.side_effect = [None, OSError("second target failed"), None, None]
    execution = _execution()
    participant = AvatarDeletionParticipant(
        operations, AvatarUploadHandler(), storage, _config()
    )
    with pytest.raises(OSError):
        await participant.run(execution)
    assert execution.avatar_evidence is None
    await participant.run(execution)
    assert execution.avatar_evidence is not None
    assert {item.kwargs["key"] for item in storage.delete.await_args_list[2:]} == set(
        execution.avatar_evidence.keys
    )


@pytest.mark.parametrize(
    "acknowledged,owned", [(False, True), (True, False), (True, True)]
)
async def test_database_completion_requires_ack_and_owned_final_transaction(
    acknowledged: bool, owned: bool
) -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    operations.runtime_acknowledged.return_value = acknowledged
    operations.finalize.return_value = owned
    execution = _execution()
    execution.avatar_evidence = AgentAvatarDeletionEvidence(
        deletion_context(execution.job, lease_owner="owner"), ()
    )
    participant = DatabaseDeletionParticipant(operations)
    if acknowledged and not owned:
        with pytest.raises(AgentDeletionOwnershipLost):
            await participant.run(execution)
    else:
        await participant.run(execution)
    assert execution.completed is (acknowledged and owned)
    if not acknowledged:
        assert execution.wait_reason is AgentDeletionWaitReason.RUNTIME_ACKNOWLEDGEMENT
        operations.finalize.assert_not_awaited()
    else:
        operations.finalize.assert_awaited_once_with(
            job=execution.job,
            lease_owner="owner",
            avatar_evidence=execution.avatar_evidence,
        )


async def test_missing_avatar_evidence_cannot_reach_root_finalization() -> None:
    operations = Mock(spec=AgentDecommissionOperationsRepository)
    with pytest.raises(RuntimeError, match="avatar evidence is missing"):
        await DatabaseDeletionParticipant(operations).run(_execution())
    operations.runtime_acknowledged.assert_not_awaited()
    operations.finalize.assert_not_awaited()
