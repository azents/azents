"""PostgreSQL coverage of the durable Vault request and completion boundary."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import SecretStr

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    AgentSessionRunState,
    EventKind,
    ExternalChannelAppMode,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    MailboxItemKind,
    MailboxSchedulingMode,
    WorkspaceUserRole,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import VaultRequestCompletionMailboxPayload
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.core.vault_request import (
    VaultRequestField,
    VaultRequestIdentityPayload,
    VaultRequestSpec,
    VaultRequestSubmission,
    VaultRequestValue,
)
from azents.core.work_context import WorkContext
from azents.rdb.models.agent_vault_request import (
    RDBAgentVaultRequest,
    VaultRequestStatus,
)
from azents.rdb.models.external_channel import RDBExternalChannelBinding
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_vault import (
    AgentVaultRepository,
    InvalidVaultEntry,
    VaultAccessDenied,
    VaultManager,
)
from azents.repos.agent_vault_requests import (
    AgentVaultRequestRepository,
    VaultRequestClosed,
    VaultRequestScope,
    read_vault_clock,
)
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelConnectionConfiguration,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import _connection_create
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxAdmissionResult, MailboxEnqueue
from azents.repos.vault_request_delivery import (
    VaultDeliveryReceipt,
    VaultRequestDeliveryRepository,
)
from azents.services.archived_session_retention_test import _create_root, _create_user


@dataclasses.dataclass(frozen=True)
class _Request:
    repo: AgentVaultRequestRepository
    vault: AgentVaultRepository
    scope: VaultRequestScope
    user_id: str
    request_id: str
    body: VaultRequestSubmission
    mailbox: MailboxRepository
    admission: MailboxAdmissionRepository

    async def submit(
        self, *, admission: MailboxAdmissionRepository | None = None
    ) -> None:
        await self.repo.submit(
            self.scope,
            self.request_id,
            self.body,
            vault=self.vault,
            admission=self.admission if admission is None else admission,
        )


@pytest.fixture
async def request_case(
    rdb_session_manager: SessionManager[WriteSession],
) -> _Request:
    manager = rdb_session_manager
    sessions = AgentSessionRepository()
    async with manager() as session:
        session_id = await _create_root(session, suffix="vault-request")
        source = await sessions.get_by_id(session, session_id)
        assert source is not None
        user_ids = {}
        for role in (WorkspaceUserRole.OWNER, WorkspaceUserRole.MEMBER):
            user_id = await _create_user(session, f"vault-{role.value}")
            session.write_session.add(
                RDBWorkspaceUser(
                    workspace_id=source.workspace_id,
                    user_id=user_id,
                    role=role,
                    name=f"Test {role.value}",
                )
            )
            user_ids[role] = user_id
        run = await AgentRunRepository().create(
            session,
            AgentRunCreate(
                session_id=session_id,
                parent_agent_run_id=None,
                work_context=WorkContext(
                    scheduled_cycle_ids=(), routine_executions=(), unrelated_input=True
                ),
            ),
        )
    vault = AgentVaultRepository(
        manager, manager, CredentialCipher(Fernet.generate_key().decode())
    )
    repo = AgentVaultRequestRepository(manager)
    anchor = await repo.create_for_execution(
        SessionResourceAuthority(
            workspace_id=source.workspace_id,
            agent_id=source.agent_id,
            session_id=session_id,
            root_session_id=session_id,
            run_id=run.id,
            run_index=run.run_index,
            owner_generation=source.owner_generation,
        ),
        VaultRequestSpec(
            purpose="Test configuration",
            fields=(
                VaultRequestField(name="login", label="Login"),
                VaultRequestField(name="password", label="Password"),
            ),
        ),
    )
    assert anchor.kind is EventKind.VAULT_REQUEST
    payload = anchor.payload
    assert isinstance(payload, VaultRequestIdentityPayload)
    async with manager() as session:
        row = await session.read_session.get(RDBAgentVaultRequest, payload.request_id)
        assert row is not None
        assert row.anchor_event_id == anchor.id
        assert row.deadline_at - row.creation_at == datetime.timedelta(hours=24)
    mailbox = MailboxRepository()
    return _Request(
        repo=repo,
        vault=vault,
        scope=VaultRequestScope(
            session_id=session_id,
            agent_id=source.agent_id,
            manager=VaultManager(
                source.workspace_id, user_ids[WorkspaceUserRole.OWNER]
            ),
        ),
        user_id=user_ids[WorkspaceUserRole.MEMBER],
        request_id=payload.request_id,
        body=VaultRequestSubmission(
            values=(
                VaultRequestValue(name="login", value=SecretStr("synthetic-login")),
                VaultRequestValue(
                    name="password", value=SecretStr("synthetic-password")
                ),
            )
        ),
        mailbox=mailbox,
        admission=MailboxAdmissionRepository(manager, mailbox, sessions),
    )


async def test_completion_is_atomic_and_remains_one_shot_after_inbox_consumption(
    request_case: _Request, rdb_session_manager: SessionManager[WriteSession]
) -> None:
    case = request_case
    view = await case.repo.get_view(case.scope, case.request_id, vault=case.vault)
    assert view.status is VaultRequestStatus.OPEN and view.can_submit
    await case.submit()
    async with rdb_session_manager() as session:
        current = await AgentSessionRepository().get_by_id(
            session, case.scope.session_id
        )
        assert current is not None and current.run_state is AgentSessionRunState.RUNNING
        items = (await session.read_session.scalars(sa.select(RDBMailboxItem))).all()
        assert len(items) == 1
        item = items[0]
        assert item.session_id == case.scope.session_id
        assert item.kind is MailboxItemKind.VAULT_REQUEST_COMPLETED
        assert item.scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
        assert item.sender_user_id is None
        payload = VaultRequestCompletionMailboxPayload.model_validate(item.payload)
        assert payload.request_id == case.request_id
        assert payload.items[0].content == ""
        await session.write_session.delete(item)
    with pytest.raises(VaultRequestClosed):
        await case.submit()
    assert (
        await case.repo.get_view(case.scope, case.request_id, vault=case.vault)
    ).status is VaultRequestStatus.SUBMITTED
    assert await case.vault.resolve_for_execution(
        case.scope.agent_id, {"password"}
    ) == {"password": SecretStr("synthetic-password")}
    async with rdb_session_manager() as session:
        assert await session.read_session.scalar(sa.select(RDBMailboxItem.id)) is None


class _RejectCompletion(MailboxAdmissionRepository):
    async def enqueue_in_session(
        self, session: WriteSession, input: MailboxEnqueue
    ) -> MailboxAdmissionResult:
        await super().enqueue_in_session(session, input)
        raise RuntimeError("Simulated post-admission failure.")


async def test_provisional_writes_rollback_and_wrong_values_cannot_write(
    request_case: _Request, rdb_session_manager: SessionManager[WriteSession]
) -> None:
    case = request_case
    failed_admission = _RejectCompletion(
        rdb_session_manager, case.mailbox, AgentSessionRepository()
    )
    with pytest.raises(RuntimeError, match="Simulated post-admission failure"):
        await case.submit(admission=failed_admission)
    first = case.body.values[0]
    with pytest.raises(InvalidVaultEntry):
        await dataclasses.replace(
            case, body=VaultRequestSubmission(values=(first, first))
        ).submit()
    assert (
        await case.vault.list_entries(case.scope.agent_id, manager=case.scope.manager)
        == []
    )
    view = await case.repo.get_view(case.scope, case.request_id, vault=case.vault)
    assert view.status is VaultRequestStatus.OPEN
    async with rdb_session_manager() as session:
        assert await session.read_session.scalar(sa.select(RDBMailboxItem.id)) is None


async def test_membership_is_not_management_and_expiry_does_not_wake(
    request_case: _Request, rdb_session_manager: SessionManager[WriteSession]
) -> None:
    case = request_case
    ordinary = dataclasses.replace(
        case.scope,
        manager=dataclasses.replace(case.scope.manager, user_id=case.user_id),
    )
    view = await case.repo.get_view(ordinary, case.request_id, vault=case.vault)
    assert view.status is VaultRequestStatus.OPEN and not view.can_submit
    with pytest.raises(VaultAccessDenied):
        await dataclasses.replace(case, scope=ordinary).submit()
    async with rdb_session_manager() as session:
        row = await session.write_session.get(RDBAgentVaultRequest, case.request_id)
        assert row is not None
        row.deadline_at = await read_vault_clock(session)
    view = await case.repo.get_view(case.scope, case.request_id, vault=case.vault)
    assert view.status is VaultRequestStatus.EXPIRED and not view.can_submit
    with pytest.raises(VaultRequestClosed):
        await case.submit()
    changes = await case.repo.expire_due(limit=1)
    assert [change.request_id for change in changes] == [case.request_id]
    assert await case.repo.expire_due(limit=1) == []
    async with rdb_session_manager() as session:
        assert await session.read_session.scalar(sa.select(RDBMailboxItem.id)) is None


async def test_late_receipt_allows_one_terminal_claim_but_never_another_create(
    request_case: _Request, rdb_session_manager: SessionManager[WriteSession]
) -> None:
    case = request_case
    delivery = VaultRequestDeliveryRepository(rdb_session_manager)
    async with rdb_session_manager() as session:
        row = await session.write_session.get(RDBAgentVaultRequest, case.request_id)
        assert row is not None
        destination: dict[str, JSONValue] = {
            "provider": "slack",
            "channel_id": "C123",
            "binding_id": "test-binding",
        }
        row.destination = destination
    assert await delivery.claim(terminal=False) == case.request_id
    assert await delivery.claim(terminal=False) is None
    async with rdb_session_manager() as session:
        row = await session.write_session.get(RDBAgentVaultRequest, case.request_id)
        assert row is not None
        row.deadline_at = await read_vault_clock(session)
    assert len(await case.repo.expire_due(limit=1)) == 1
    assert await delivery.claim(terminal=True) is None
    receipt = VaultDeliveryReceipt(
        connection_id="test-connection",
        provider=ExternalChannelProvider.SLACK,
        tenant_id="T123",
        app_id="A123",
        bot_id="U123",
        channel_id="C123",
        provider_message_key="slack:T123:C123:12345.6789",
    )
    await delivery.record_receipt(case.request_id, receipt)
    await delivery.record_receipt(
        case.request_id, receipt.model_copy(update={"provider_message_key": "other"})
    )
    assert await delivery.claim(terminal=True) == case.request_id
    assert await delivery.claim(terminal=True) is None
    # An unverified route can trigger neither effect even after the claim.
    assert await delivery.read_target(case.request_id, terminal=True) is None
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBAgentVaultRequest, case.request_id)
        assert row is not None and row.receipt == receipt.model_dump(mode="json")
        assert row.status is VaultRequestStatus.EXPIRED


@pytest.mark.parametrize(
    ("provider", "channel"),
    [
        (ExternalChannelProvider.DISCORD, "123456789"),
        (ExternalChannelProvider.SLACK, "C123"),
    ],
)
async def test_claim_rechecks_exact_connected_binding(
    request_case: _Request,
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    provider: ExternalChannelProvider,
    channel: str,
) -> None:
    case = request_case
    external = ExternalChannelRepository()
    delivery = VaultRequestDeliveryRepository(rdb_session_manager)
    async with rdb_session_manager() as session:
        connection = await external.create_connection(
            session,
            _connection_create(case.scope.manager.workspace_id).model_copy(
                update={
                    "provider": provider,
                    "provider_tenant_id": "456",
                    "provider_bot_user_id": "789",
                }
            ),
        )
        route = await external.create_agent_route(
            session,
            ExternalChannelAgentRouteCreate(
                connection_id=connection.id,
                agent_id=case.scope.agent_id,
                agent_id_snapshot=case.scope.agent_id,
                route_mode=ExternalChannelRouteMode.DEDICATED,
                connection_app_mode=ExternalChannelAppMode.SINGLE,
                catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                catalog_removed_at=None,
                catalog_removed_by_user_id=None,
            ),
        )
        resource = await external.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=connection.id,
                resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                provider_resource_key=channel,
                labels=None,
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=None,
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        binding = await external.create_binding_idempotent(
            session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=route.id,
                agent_session_id=case.scope.session_id,
                response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_access_request_id=None,
        )
        row = await session.write_session.get(RDBAgentVaultRequest, case.request_id)
        assert row is not None
        destination: dict[str, JSONValue] = {
            "provider": provider.value,
            "channel_id": channel,
            "binding_id": binding.id,
        }
        row.destination = destination

    assert await delivery.claim(terminal=False) == case.request_id
    target = await delivery.read_target(case.request_id, terminal=False)
    assert target is not None and target.channel_id == channel
    assert target.purpose == "Test configuration"
    assert target.field_labels == ("Login", "Password")
    original_get_configuration = ExternalChannelRepository.get_connection_configuration

    async def disconnect_after_target_read(
        repository: ExternalChannelRepository,
        session: WriteSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        snapshot = await original_get_configuration(
            repository, session, connection_id=connection_id
        )
        await session.write_session.execute(
            sa.update(RDBExternalChannelBinding)
            .where(RDBExternalChannelBinding.id == binding.id)
            .values(disconnected_at=await read_vault_clock(session))
        )
        return snapshot

    monkeypatch.setattr(
        ExternalChannelRepository,
        "get_connection_configuration",
        disconnect_after_target_read,
    )
    assert await delivery.read_target(case.request_id, terminal=False) is None
