"""Completed database operations for Engine Subagent collaboration tools."""

import dataclasses
from textwrap import dedent
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import SubagentSettings
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    AgentSessionStatus,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionAgentKind,
)
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.types import AgentRunState, Event
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItemCreate
from azents.repos.model_metadata_source import ModelMetadataSourceRepository
from azents.repos.model_metadata_source_data import ModelMetadataSourceSnapshot
from azents.repos.subagent_coordination.data import SubagentCoordinationSnapshot
from azents.repos.subagent_coordination.repository import (
    SubagentCoordinationRepository,
)
from azents.services.model_metadata_source import GENAI_PRICES_SOURCE_KEY


class SubagentToolOperationError(ValueError):
    """A Subagent database operation failed a model-visible precondition."""


@dataclasses.dataclass(frozen=True)
class SubagentSpawnPreparation:
    """Detached inputs for pure spawn inference and fork projection."""

    current: SessionAgent
    parent_run: AgentRunState
    parent_session: AgentSession
    agent: Agent
    events: list[Event]


@dataclasses.dataclass(frozen=True)
class SubagentSpawnResult:
    """Committed child identity and wake target."""

    child: SessionAgent
    child_session: AgentSession


@dataclasses.dataclass(frozen=True)
class SubagentTargetResult:
    """Committed target resolution for post-commit effects."""

    target: SessionAgent | None
    target_session: AgentSession | None = None
    previous_status: str | None = None
    signal_stop: bool = False


class SubagentResolvedTarget(NamedTuple):
    """Current SessionAgent and an optionally resolved collaboration target."""

    current: SessionAgent
    target: SessionAgent | None


@dataclasses.dataclass
class SubagentToolOperationRepository:
    """Own complete Subagent collaboration database transactions."""

    session_manager: SessionManager[AsyncSession]
    agent_repository: AgentRepository
    agent_session_repository: AgentSessionRepository
    agent_run_repository: AgentRunRepository
    event_transcript_repository: EventTranscriptRepository
    mailbox_repository: MailboxRepository
    source_snapshot_repository: ModelMetadataSourceRepository
    coordination_repository: SubagentCoordinationRepository

    async def get_agent(self, agent_id: str) -> Agent | None:
        """Return one current Agent policy snapshot."""
        async with self.session_manager() as session:
            return await self.agent_repository.get_by_id(session, agent_id)

    async def get_current_session_agent(
        self,
        session_id: str,
    ) -> SessionAgent | None:
        """Return the SessionAgent linked to one current Session."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.get_session_agent_by_session_id(
                session,
                session_id,
            )

    async def load_model_source_snapshot(self) -> ModelMetadataSourceSnapshot | None:
        """Return the latest validated model metadata source snapshot."""
        async with self.session_manager() as session:
            return await self.source_snapshot_repository.get_current(
                session,
                source_key=GENAI_PRICES_SOURCE_KEY,
            )

    async def prepare_spawn(
        self,
        *,
        session_id: str,
        agent_id: str,
        parent_run_id: str,
        settings: SubagentSettings,
    ) -> SubagentSpawnPreparation:
        """Load and validate detached spawn inputs in one read transaction."""
        async with self.session_manager() as session:
            current = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            if current is None:
                raise SubagentToolOperationError("Current SessionAgent was not found")
            next_depth = _session_agent_depth(current) + 1
            if next_depth > settings.max_depth:
                raise SubagentToolOperationError(
                    "Cannot spawn subagent: max_depth "
                    f"{settings.max_depth} would be exceeded by child depth "
                    f"{next_depth}."
                )
            parent_run = await self.agent_run_repository.get_by_id(
                session,
                parent_run_id,
            )
            if parent_run is None or parent_run.session_id != current.agent_session_id:
                raise SubagentToolOperationError("Current AgentRun was not found")
            if parent_run.status != AgentRunStatus.RUNNING:
                raise SubagentToolOperationError("Current AgentRun is not running")
            parent_session = await self.agent_session_repository.get_by_id(
                session,
                current.agent_session_id,
            )
            if parent_session is None:
                raise SubagentToolOperationError("AgentSession was not found")
            if parent_session.inference_state is None:
                raise SubagentToolOperationError(
                    "Current Session has no prepared inference state"
                )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                raise SubagentToolOperationError("Agent was not found")
            events = await self.event_transcript_repository.list_for_model_input(
                session,
                current.agent_session_id,
                head_event_id=parent_session.model_input_head_event_id,
            )
            return SubagentSpawnPreparation(
                current=current,
                parent_run=parent_run,
                parent_session=parent_session,
                agent=agent,
                events=events,
            )

    async def spawn(
        self,
        *,
        session_id: str,
        parent_run_id: str,
        settings: SubagentSettings,
        name: str,
        agent_type: str,
        task: str,
        profile: SessionInferenceState,
        forked_events: list[Event],
    ) -> SubagentSpawnResult:
        """Create one child, Run, transcript, and assignment atomically."""
        async with self.session_manager() as session:
            current = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            if current is None:
                raise SubagentToolOperationError("Current SessionAgent was not found")
            next_depth = _session_agent_depth(current) + 1
            if next_depth > settings.max_depth:
                raise SubagentToolOperationError(
                    "Cannot spawn subagent: max_depth "
                    f"{settings.max_depth} would be exceeded by child depth "
                    f"{next_depth}."
                )
            active_ids = await self._lock_and_list_active_subagent_ids(
                session,
                current=current,
            )
            if len(active_ids) >= settings.max_subagents:
                raise SubagentToolOperationError(
                    "Cannot spawn subagent: max_subagents "
                    f"{settings.max_subagents} is already reached for this root "
                    "session."
                )
            parent_run = await self.agent_run_repository.get_by_id(
                session,
                parent_run_id,
            )
            if parent_run is None or parent_run.session_id != current.agent_session_id:
                raise SubagentToolOperationError("Current AgentRun was not found")
            if parent_run.status != AgentRunStatus.RUNNING:
                raise SubagentToolOperationError("Current AgentRun is not running")
            parent_session = await self.agent_session_repository.get_by_id(
                session,
                current.agent_session_id,
            )
            if parent_session is None:
                raise SubagentToolOperationError("AgentSession was not found")
            if parent_session.inference_state is None:
                raise SubagentToolOperationError(
                    "Current Session has no prepared inference state"
                )
            try:
                child = await self.agent_session_repository.create_child_session_agent(
                    session,
                    parent_session_agent_id=current.id,
                    name=name,
                    agent_type=agent_type,
                    title=name,
                    last_task_message=task,
                )
            except ValueError as exc:
                raise SubagentToolOperationError(str(exc)) from None
            child_session = await self.agent_session_repository.get_by_id(
                session,
                child.agent_session_id,
            )
            if child_session is None:
                raise SubagentToolOperationError("AgentSession was not found")
            await self.agent_run_repository.create_pending(
                session,
                session_id=child.agent_session_id,
                parent_agent_run_id=parent_run.id,
                scheduled_task_cycle_id=None,
            )
            await self.agent_session_repository.set_applied_inference_profile(
                session,
                session_id=child.agent_session_id,
                model_target_label=profile.model_target_label,
                reasoning_effort=profile.reasoning_effort,
                enabled_execution_options=profile.enabled_execution_options,
            )
            await self.agent_session_repository.set_inference_state(
                session,
                session_id=child.agent_session_id,
                inference_state=profile,
            )
            for event in forked_events:
                await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=child.agent_session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                    ),
                )
            if forked_events:
                await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=child.agent_session_id,
                        kind=EventKind.SYSTEM_REMINDER,
                        payload={"text": _fork_boundary_text(child)},
                    ),
                )
            await self._enqueue_instruction(
                session,
                source=current,
                target=child,
                content=task,
                message_kind="spawn_agent",
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            )
            return SubagentSpawnResult(
                child=child,
                child_session=child_session,
            )

    async def send_message(
        self,
        *,
        session_id: str,
        agent_name: str,
        content: str,
    ) -> SubagentTargetResult:
        """Queue one message in a completed transaction."""
        async with self.session_manager() as session:
            current, target = await self._resolve_target(
                session,
                session_id=session_id,
                agent_name=agent_name,
            )
            if target is None:
                return SubagentTargetResult(target=None)
            await self._enqueue_instruction(
                session,
                source=current,
                target=target,
                content=content,
                message_kind="send_message",
                scheduling_mode=MailboxSchedulingMode.QUEUE_ONLY,
            )
            await self.agent_session_repository.update_session_agent_last_task_message(
                session,
                session_agent_id=target.id,
                last_task_message=content,
            )
            return SubagentTargetResult(target=target)

    async def followup_task(
        self,
        *,
        session_id: str,
        agent_name: str,
        content: str,
        max_subagents: int,
    ) -> SubagentTargetResult:
        """Assign and admit one follow-up task atomically."""
        async with self.session_manager() as session:
            current, target = await self._resolve_target(
                session,
                session_id=session_id,
                agent_name=agent_name,
            )
            if target is None:
                return SubagentTargetResult(target=None)
            if target.kind == SessionAgentKind.ROOT:
                raise SubagentToolOperationError(
                    "Follow-up tasks can't target the root agent"
                )
            active_ids = await self._lock_and_list_active_subagent_ids(
                session,
                current=current,
            )
            if target.id not in active_ids and len(active_ids) >= max_subagents:
                raise SubagentToolOperationError(
                    "Cannot assign follow-up task: max_subagents "
                    f"{max_subagents} is already reached for this root session."
                )
            target_session = await self.agent_session_repository.get_by_id(
                session,
                target.agent_session_id,
            )
            if target_session is None:
                raise SubagentToolOperationError("AgentSession was not found")
            await self._enqueue_instruction(
                session,
                source=current,
                target=target,
                content=content,
                message_kind="followup_task",
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            )
            await self.agent_session_repository.update_session_agent_last_task_message(
                session,
                session_agent_id=target.id,
                last_task_message=content,
            )
            return SubagentTargetResult(
                target=target,
                target_session=target_session,
            )

    async def interrupt(
        self,
        *,
        session_id: str,
        agent_name: str,
    ) -> SubagentTargetResult:
        """Persist one child interruption request in a completed transaction."""
        async with self.session_manager() as session:
            current, target = await self._resolve_target(
                session,
                session_id=session_id,
                agent_name=agent_name,
            )
            if target is None:
                return SubagentTargetResult(
                    target=None,
                    previous_status="not_found",
                )
            if target.kind == SessionAgentKind.ROOT:
                raise SubagentToolOperationError("root is not a spawned agent")
            if target.id == current.id:
                raise SubagentToolOperationError(
                    "an agent cannot interrupt itself; return your result and let "
                    "the parent interrupt you if needed"
                )
            locked_root = await self.agent_session_repository.lock_session_agent_by_id(
                session,
                current.root_session_agent_id,
            )
            if locked_root is None:
                raise SubagentToolOperationError("Root SessionAgent was not found")
            target_session = await self.agent_session_repository.lock_by_id(
                session,
                target.agent_session_id,
            )
            if target_session is None:
                raise SubagentToolOperationError("AgentSession was not found")
            previous_status = await self._project_agent_status(session, target)
            signal_stop = target_session.run_state == AgentSessionRunState.RUNNING
            if signal_stop:
                await self.agent_session_repository.request_stop(
                    session,
                    session_id=target_session.id,
                    stop_request_id="subagent_interrupt",
                    stop_requester_user_id=None,
                )
            return SubagentTargetResult(
                target=target,
                target_session=target_session,
                previous_status=previous_status,
                signal_stop=signal_stop,
            )

    async def list_agents(
        self,
        *,
        session_id: str,
        configured_capacity: int,
    ) -> SubagentCoordinationSnapshot | None:
        """Return one bounded coordination snapshot."""
        async with self.session_manager() as session:
            return await self.coordination_repository.project_root_tree(
                session,
                current_session_id=session_id,
                configured_capacity=configured_capacity,
            )

    async def _resolve_target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_name: str,
    ) -> SubagentResolvedTarget:
        current = await self.agent_session_repository.get_session_agent_by_session_id(
            session,
            session_id,
        )
        if current is None:
            raise SubagentToolOperationError("Current SessionAgent was not found")
        try:
            target = await self.agent_session_repository.resolve_session_agent_path(
                session,
                current_session_agent_id=current.id,
                path=agent_name,
            )
        except ValueError:
            target = None
        return SubagentResolvedTarget(current=current, target=target)

    async def _lock_and_list_active_subagent_ids(
        self,
        session: AsyncSession,
        *,
        current: SessionAgent,
    ) -> set[str]:
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            current.root_session_agent_id,
        )
        if locked_root is None:
            raise SubagentToolOperationError("Root SessionAgent was not found")
        tree = await self.agent_session_repository.list_session_agent_tree(
            session,
            root_session_agent_id=current.root_session_agent_id,
        )
        subagents = [
            agent for agent in tree if agent.id != current.root_session_agent_id
        ]
        sessions = await self.agent_session_repository.list_by_ids(
            session,
            agent_session_ids=[agent.agent_session_id for agent in subagents],
        )
        latest_runs = await self.agent_run_repository.list_latest_by_session_ids(
            session,
            session_ids=[agent.agent_session_id for agent in subagents],
        )
        return {
            agent.id
            for agent in subagents
            if _session_agent_active(
                sessions.get(agent.agent_session_id),
                latest_runs.get(agent.agent_session_id),
            )
        }

    async def _enqueue_instruction(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        content: str,
        message_kind: str,
        scheduling_mode: MailboxSchedulingMode,
    ) -> None:
        if source.root_session_agent_id != target.root_session_agent_id:
            raise SubagentToolOperationError(
                "Mailbox agents must belong to the same root tree"
            )
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            source.root_session_agent_id,
        )
        if locked_root is None:
            raise SubagentToolOperationError("Root SessionAgent not found")
        locked_target = await self.agent_session_repository.lock_by_id(
            session,
            target.agent_session_id,
        )
        if locked_target is None:
            raise SubagentToolOperationError("Target AgentSession not found")
        if locked_target.status is not AgentSessionStatus.ACTIVE:
            raise SubagentToolOperationError("Target AgentSession is not active")
        if (
            scheduling_mode is MailboxSchedulingMode.WAKE_SESSION
            and locked_target.stop_requested_at is not None
        ):
            raise SubagentToolOperationError("Target AgentSession is stopping")
        metadata = {
            "source": "agent_mailbox",
            "message_kind": message_kind,
            "source_session_agent_id": source.id,
            "source_path": source.path,
            "target_session_agent_id": target.id,
            "target_path": target.path,
        }
        await self.mailbox_repository.create(
            session,
            MailboxItemCreate(
                session_id=target.agent_session_id,
                kind=MailboxItemKind.AGENT_MESSAGE,
                scheduling_mode=scheduling_mode,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content=content,
                idempotency_key=None,
                metadata=metadata,
                action=None,
                attachments=[],
                file_parts=[],
            ),
        )
        if scheduling_mode is MailboxSchedulingMode.WAKE_SESSION:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                target.agent_session_id,
            )
        mark_activity = (
            self.agent_session_repository.mark_session_agent_message_activity
        )
        await mark_activity(session, session_agent_id=source.id)
        if target.id != source.id:
            await mark_activity(session, session_agent_id=target.id)

    async def _project_agent_status(
        self,
        session: AsyncSession,
        agent: SessionAgent,
    ) -> str:
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            agent.agent_session_id,
        )
        if agent_session is None:
            return "not_found"
        if agent_session.run_state == AgentSessionRunState.RUNNING:
            return "running"
        latest = await self.agent_run_repository.list_latest_by_session_ids(
            session,
            session_ids=[agent.agent_session_id],
        )
        run = latest.get(agent.agent_session_id)
        if run is None:
            return "idle"
        return _run_status(run.status)


def _session_agent_depth(agent: SessionAgent) -> int:
    if agent.path == "/root":
        return 0
    return len([segment for segment in agent.path.split("/") if segment]) - 1


def _session_agent_active(
    session: AgentSession | None,
    latest_run: AgentRunState | None,
) -> bool:
    if session is None:
        return False
    return session.run_state == AgentSessionRunState.RUNNING or (
        latest_run is not None
        and latest_run.status in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
    )


def _run_status(status: AgentRunStatus) -> str:
    if status == AgentRunStatus.COMPLETED:
        return "completed"
    if status == AgentRunStatus.FAILED:
        return "errored"
    if status in {
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return "interrupted"
    return status.value


def _fork_boundary_text(child: SessionAgent) -> str:
    return dedent(
        f"""\
        The messages above are inherited conversation history from the parent
        agent. They reflect the parent agent's earlier perspective and are
        background context only.

        You are the subagent named "{child.name}".
        Your full agent path is "{child.path}".
        The next message is your current direct assignment.

        Do not treat agent identities or tool calls in the inherited history as
        your own actions. Never call wait on yourself. wait is only
        for observing your descendants.
        """
    )
