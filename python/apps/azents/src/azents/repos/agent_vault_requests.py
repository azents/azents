"""Database-only Agent Vault request lifecycle operations."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing
from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import (
    MailboxPresentationItem,
    VaultRequestCompletionMailboxPayload,
)
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.core.vault_request import (
    VaultRequestField,
    VaultRequestSpec,
    VaultRequestSubmission,
)
from azents.engine.events.types import Event
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_vault_request import (
    RDBAgentVaultRequest,
    VaultRequestStatus,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_vault import (
    AgentVaultRepository,
    InvalidVaultEntry,
    VaultAccessDenied,
    VaultManager,
    fence_vault_execution_write,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxEnqueue
from azents.repos.session_resource_authority import (
    AuthorizedPublicSessionResource,
    authorize_public_session_resource,
)
from azents.repos.workspace_user import WorkspaceUserRepository

_REQUEST_LIFETIME = datetime.timedelta(hours=24)


@dataclasses.dataclass(frozen=True)
class VaultRequestScope:
    """The exact chat tuple and its authenticated Workspace principal."""

    session_id: str
    agent_id: str
    manager: VaultManager


@dataclasses.dataclass(frozen=True)
class VaultRequestView:
    """Value-free current request state, including immediate effective expiry."""

    request_id: str
    purpose: str
    fields: tuple[VaultRequestField, ...]
    status: VaultRequestStatus
    deadline_at: datetime.datetime
    can_submit: bool


@dataclasses.dataclass(frozen=True)
class VaultRequestChange:
    """Routing-only notification of committed request settlement."""

    session_id: str
    request_id: str


class VaultRequestClosed(Exception):
    """No more submissions are accepted for this request."""


def _request_state(
    row: RDBAgentVaultRequest, now: datetime.datetime
) -> VaultRequestStatus:
    if row.status is VaultRequestStatus.OPEN and now >= row.deadline_at:
        return VaultRequestStatus.EXPIRED
    return row.status


async def _authorize(
    session: WriteSession,
    scope: VaultRequestScope,
    source: AgentSession | None,
) -> AuthorizedPublicSessionResource:
    if source is not None:
        result = await authorize_public_session_resource(
            session,
            agent_session=source,
            user_id=scope.manager.user_id,
            require_active=True,
            denied_as_not_found=True,
            expected_workspace_id=scope.manager.workspace_id,
            expected_agent_id=scope.agent_id,
            agent_session_repository=AgentSessionRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
        )
        if isinstance(result, AuthorizedPublicSessionResource):
            return result
    raise VaultAccessDenied("Vault request not found.")


async def read_vault_clock(session: ReadSession) -> datetime.datetime:
    """Read elapsed PostgreSQL time, including time spent waiting on locks."""
    now = await session.read_session.scalar(sa.select(sa.func.clock_timestamp()))
    assert isinstance(now, datetime.datetime)
    return now


async def project_vault_history_cards(
    session: ReadSession, *, source: AgentSession, items: list[Event]
) -> dict[str, dict[str, object]]:
    """Batch-read safe state for anchors in the already authorized history page."""
    anchors = [item.id for item in items if item.kind is EventKind.VAULT_REQUEST]
    if not anchors:
        return {}
    active = sa.exists().where(
        RDBAgent.id == source.agent_id,
        RDBAgent.workspace_id == source.workspace_id,
        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
    )
    rows = await session.read_session.scalars(
        sa.select(RDBAgentVaultRequest).where(
            RDBAgentVaultRequest.session_id == source.id,
            RDBAgentVaultRequest.anchor_event_id.in_(anchors),
            active,
        )
    )
    now = await read_vault_clock(session)
    return {
        row.anchor_event_id: {
            "request_id": row.id,
            "purpose": row.purpose,
            "fields": [
                VaultRequestField.model_validate(field).model_dump(mode="json")
                for field in row.fields
            ],
            "status": _request_state(row, now).value,
            "deadline_at": row.deadline_at.isoformat(),
            # History is not an authorization surface for the input dialog.
            "can_submit": False,
        }
        for row in rows
    }


@dataclasses.dataclass(frozen=True)
class AgentVaultRequestRepository:
    """Own request persistence; keep provider and broker I/O outside its writes."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def create_for_execution(
        self, authority: SessionResourceAuthority, spec: VaultRequestSpec
    ) -> Event:
        """Commit one request and its value-free history placement together."""
        async with self.session_manager() as session:
            source = await fence_vault_execution_write(session, authority)
            destination: dict[str, JSONValue] | None = None
            if spec.destination is not None:
                binding = (
                    await ExternalChannelRepository().find_exact_connected_channel(
                        session,
                        workspace_id=source.workspace_id,
                        agent_id=source.agent_id,
                        provider=spec.destination.provider,
                        channel_id=spec.destination.channel_id,
                    )
                )
                if binding is None:
                    raise VaultAccessDenied("Vault request destination is unavailable.")
                destination = {
                    "provider": spec.destination.provider.value,
                    "channel_id": spec.destination.channel_id,
                    "binding_id": binding.id,
                }
            now = await read_vault_clock(session)
            request_id = uuid7().hex
            anchor = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=source.id,
                    kind=EventKind.VAULT_REQUEST,
                    payload={"request_id": request_id},
                ),
            )
            row = RDBAgentVaultRequest(
                session_id=source.id,
                anchor_event_id=anchor.id,
                purpose=spec.purpose,
                fields=[
                    {"name": item.name, "label": item.label} for item in spec.fields
                ],
                creation_at=now,
                deadline_at=now + _REQUEST_LIFETIME,
                destination=destination,
                button_label=spec.button_label,
            )
            row.id = request_id
            session.write_session.add(row)
            return anchor

    async def get_view(
        self,
        scope: VaultRequestScope,
        request_id: str,
        *,
        vault: AgentVaultRepository,
    ) -> VaultRequestView:
        """Read authorized metadata without projecting values or delivery state."""
        async with self.session_manager() as session:
            source = await AgentSessionRepository().get_by_id(session, scope.session_id)
            authorized = await _authorize(session, scope, source)
            active_agent = await session.read_session.scalar(
                sa.select(RDBAgent.id).where(
                    RDBAgent.id == scope.agent_id,
                    RDBAgent.workspace_id == scope.manager.workspace_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                )
            )
            if active_agent is None:
                raise VaultAccessDenied("Vault request not found.")
            row = await session.read_session.scalar(
                sa.select(RDBAgentVaultRequest).where(
                    RDBAgentVaultRequest.session_id == scope.session_id,
                    RDBAgentVaultRequest.id == request_id,
                )
            )
            if row is None:
                raise VaultAccessDenied("Vault request not found.")
            can_manage = await vault.can_manage_in_session(
                session, agent_id=scope.agent_id, manager=scope.manager
            )
            status = _request_state(row, await read_vault_clock(session))
            return VaultRequestView(
                request_id=row.id,
                purpose=row.purpose,
                fields=tuple(
                    VaultRequestField.model_validate(item) for item in row.fields
                ),
                status=status,
                deadline_at=row.deadline_at,
                can_submit=(
                    status is VaultRequestStatus.OPEN
                    and can_manage
                    and authorized.session.stop_requested_at is None
                    and authorized.root_session.stop_requested_at is None
                ),
            )

    async def submit(
        self,
        scope: VaultRequestScope,
        request_id: str,
        submission: VaultRequestSubmission,
        *,
        vault: AgentVaultRepository,
        admission: MailboxAdmissionRepository,
    ) -> None:
        """Atomically commit encrypted values and one original-Session completion."""
        sessions = AgentSessionRepository()
        async with self.session_manager() as session:
            source = await sessions.get_by_id(session, scope.session_id)
            checked = await _authorize(session, scope, source)
            # Do not take an Agent write lock for an unauthorized caller.
            if not await vault.can_manage_in_session(
                session, agent_id=scope.agent_id, manager=scope.manager
            ):
                raise VaultAccessDenied("Vault request not found.")
            try:
                contributor = await vault.fence_manager_write_in_session(
                    session, agent_id=scope.agent_id, manager=scope.manager
                )
            except AgentMutationReadOnly, AgentMutationTargetMissing:
                raise VaultAccessDenied("Vault request not found.") from None
            tree = await sessions.lock_root_tree_sessions(
                session, root_session_id=checked.root_session.id
            )
            by_id = {item.id: item for item in tree}
            authorized = await _authorize(session, scope, by_id.get(scope.session_id))
            root = by_id.get(authorized.root_session.id)
            if root is None or root.status is not AgentSessionStatus.ACTIVE:
                raise VaultAccessDenied("Vault request not found.")
            if (
                root.stop_requested_at is not None
                or authorized.session.stop_requested_at is not None
            ):
                raise VaultRequestClosed("Vault request cannot be submitted now.")
            row = await session.write_session.scalar(
                sa.select(RDBAgentVaultRequest)
                .where(
                    RDBAgentVaultRequest.id == request_id,
                    RDBAgentVaultRequest.session_id == scope.session_id,
                )
                .with_for_update()
            )
            if row is None:
                raise VaultAccessDenied("Vault request not found.")
            values = {field.name: field.value for field in submission.values}
            if len(values) != len(submission.values) or values.keys() != {
                VaultRequestField.model_validate(field).name for field in row.fields
            }:
                raise InvalidVaultEntry("Invalid Vault request fields.")
            now = await read_vault_clock(session)
            if _request_state(row, now) is not VaultRequestStatus.OPEN:
                raise VaultRequestClosed("Vault request is closed.")
            await vault.apply_manager_batch_in_session(
                session,
                scope.agent_id,
                values,
                manager=scope.manager,
                contributor_label=contributor,
            )
            row.status = VaultRequestStatus.SUBMITTED
            row.terminal_at = now
            kind = MailboxItemKind.VAULT_REQUEST_COMPLETED
            await admission.enqueue_in_session(
                session,
                MailboxEnqueue(
                    session_id=scope.session_id,
                    kind=kind,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="",
                    idempotency_key=f"vault-request:{request_id}",
                    metadata={},
                    attachments=[],
                    file_parts=[],
                    action=None,
                    payload=VaultRequestCompletionMailboxPayload(
                        type=kind.value,
                        request_id=request_id,
                        items=[
                            MailboxPresentationItem(
                                item_key=f"{kind.value}:0",
                                presentation_kind=kind.value,
                                content="",
                            )
                        ],
                    ),
                ),
            )

    async def expire_due(self, *, limit: int) -> list[VaultRequestChange]:
        """Settle a bounded batch without waiting on concurrent submissions."""
        if limit <= 0:
            raise ValueError("Vault expiry batch limit must be positive.")
        async with self.session_manager() as session:
            now = await read_vault_clock(session)
            candidates = (
                sa.select(RDBAgentVaultRequest.id)
                .where(
                    RDBAgentVaultRequest.status == VaultRequestStatus.OPEN,
                    RDBAgentVaultRequest.deadline_at <= now,
                )
                .order_by(RDBAgentVaultRequest.deadline_at, RDBAgentVaultRequest.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .cte("due_vault_requests")
            )
            settled = await session.write_session.execute(
                sa.update(RDBAgentVaultRequest)
                .where(RDBAgentVaultRequest.id.in_(sa.select(candidates.c.id)))
                .values(status=VaultRequestStatus.EXPIRED, terminal_at=now)
                .returning(RDBAgentVaultRequest.session_id, RDBAgentVaultRequest.id)
            )
            return [
                VaultRequestChange(session_id=session_id, request_id=request_id)
                for session_id, request_id in settled.all()
            ]
