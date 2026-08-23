"""Closed TurnAction capability policy, discovery, and preparation."""

import dataclasses
import datetime
import enum
import logging
from typing import Annotated, Literal, Protocol, assert_never

from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState, EventKind
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CleanupOrphanGitWorktreesAction,
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
    GoalAction,
    OperationAction,
    PublicTurnAction,
    SkillAction,
    TurnAction,
)
from azents.engine.events.types import SkillLoadedPayload
from azents.engine.tools.deps import (
    get_goal_state_store,
    get_skill_state_store,
    get_vfs_projection_service,
)
from azents.engine.tools.goal import GoalState, GoalStateSnapshot, GoalStateStore
from azents.engine.tools.skill import (
    SkillActionProjectionReader,
    SkillProjectionItem,
    SkillStateStore,
    load_skill_projection_for_actions,
    resolve_active_skill,
    skill_action_id,
    skill_actions_from_snapshot,
    skill_item_from_vfs_entry,
)
from azents.rdb.models.event import JSONValue
from azents.repos.agent_session import AgentSessionRepository
from azents.services.vfs import (
    VfsFileResolutionError,
    VfsResolvedFile,
)

logger = logging.getLogger(__name__)
_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])
_TURN_ACTION_ADAPTER = TypeAdapter(TurnAction)

TurnActionVisibility = Literal["composer", "direct", "internal"]
TurnActionMessagePolicy = Literal["none", "optional", "required"]
TurnActionAttachmentPolicy = Literal["unsupported", "optional", "required"]


class TurnActionVfsProjectionService(SkillActionProjectionReader, Protocol):
    """Managed VFS operations required by TurnAction capabilities."""

    async def resolve_file(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        uri: str,
    ) -> VfsResolvedFile:
        """Resolve one exact managed file."""
        ...


@dataclasses.dataclass(frozen=True)
class TurnActionPolicy:
    """Shared policy for one closed TurnAction type."""

    action_type: str
    owner: str
    visibility: TurnActionVisibility
    message_policy: TurnActionMessagePolicy
    message_max_length: int | None
    attachment_policy: TurnActionAttachmentPolicy
    admission_profile_required: bool
    preparation_inference_required: bool
    operation: bool


@dataclasses.dataclass(frozen=True)
class TurnActionAvailabilityHint:
    """Non-authoritative action availability presentation."""

    state: Literal["ready", "warning"]
    message: str | None


@dataclasses.dataclass(frozen=True)
class TurnActionDefinition:
    """Domain composer definition for one public TurnAction."""

    id: str
    keyword: str
    label: str
    description: str
    message_placeholder: str | None
    action: PublicTurnAction
    policy: TurnActionPolicy
    availability_hint: TurnActionAvailabilityHint | None
    source_label: str | None
    relative_hint: str | None


@dataclasses.dataclass(frozen=True)
class TurnActionCatalogContext:
    """Authorized Session context for composer action discovery."""

    agent_id: str
    session_id: str
    workspace_id: str
    run_state: AgentSessionRunState
    active_run_id: str | None
    goal_in_progress: bool


class TurnActionPreparationEffect(enum.StrEnum):
    """Effect of one TurnAction preparation on model-turn eligibility."""

    ELIGIBLE = "eligible"
    NEUTRAL = "neutral"
    FAILED = "failed"


@dataclasses.dataclass(frozen=True)
class TurnActionPreparedEvent:
    """One semantic event returned by an action owner."""

    kind: EventKind
    payload: dict[str, JSONValue]
    external_id_suffix: str


@dataclasses.dataclass(frozen=True)
class TurnActionPreparationContext:
    """Caller-owned transaction and immutable action input snapshot."""

    session: AsyncSession
    session_id: str
    active_run_id: str | None
    mailbox_item_id: str
    content: str


@dataclasses.dataclass(frozen=True)
class TurnActionPreparationResult:
    """Typed semantic preparation result for one TurnAction."""

    events: list[TurnActionPreparedEvent]
    append_user_message: bool
    effect: TurnActionPreparationEffect
    handled_failure: str | None
    operation_action: OperationAction | None


class TurnActionAdmissionError(ValueError):
    """Public TurnAction input violates its registered policy."""


@dataclasses.dataclass(frozen=True)
class TurnActionCapabilityRegistry:
    """Explicit closed registry for TurnAction lifecycle capabilities."""

    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    goal_store: Annotated[GoalStateStore, Depends(get_goal_state_store)]
    skill_store: Annotated[SkillStateStore, Depends(get_skill_state_store)]
    vfs_projection_service: Annotated[
        TurnActionVfsProjectionService | None,
        Depends(get_vfs_projection_service),
    ]

    def decode(self, value: object) -> TurnAction:
        """Decode one persisted typed TurnAction."""
        return _TURN_ACTION_ADAPTER.validate_python(value)

    def policy_for(self, action: TurnAction) -> TurnActionPolicy:
        """Return the shared policy for one typed action."""
        match action:
            case GoalAction():
                return _GOAL_POLICY
            case SkillAction():
                return _SKILL_POLICY
            case CreateGitWorktreeAction():
                return _CREATE_GIT_WORKTREE_POLICY
            case CleanupOrphanGitWorktreesAction():
                return _CLEANUP_WORKTREES_POLICY
            case CreateSessionWorkingFolderAction():
                return _CREATE_SESSION_WORKING_FOLDER_POLICY
            case AgentCreateGitWorktreeAction():
                return _AGENT_CREATE_GIT_WORKTREE_POLICY
            case AgentRemoveGitWorktreeAction():
                return _AGENT_REMOVE_GIT_WORKTREE_POLICY
            case _:
                assert_never(action)

    def validate_public_input(
        self,
        *,
        action: PublicTurnAction,
        message: str,
        attachments: list[str] | None,
        inference_profile: RequestedInferenceProfile | None,
    ) -> RequestedInferenceProfile:
        """Validate one public action input against its shared policy."""
        policy = self.policy_for(action)
        if policy.visibility == "internal":
            raise TurnActionAdmissionError("This action is not supported.")
        if policy.admission_profile_required and inference_profile is None:
            raise TurnActionAdmissionError(
                "Run-producing input requires an inference profile."
            )
        if attachments and policy.attachment_policy == "unsupported":
            raise TurnActionAdmissionError("This action does not support attachments.")
        stripped = message.strip()
        if policy.message_policy == "required" and not stripped:
            raise TurnActionAdmissionError("Goal objective is required.")
        if (
            policy.message_max_length is not None
            and len(message) > policy.message_max_length
        ):
            raise TurnActionAdmissionError(
                "Action message must be "
                f"{policy.message_max_length} characters or fewer."
            )
        if inference_profile is None:
            raise TurnActionAdmissionError(
                "Run-producing input requires an inference profile."
            )
        return inference_profile

    def preparation_requires_inference(self, action: TurnAction) -> bool:
        """Return whether action preparation needs a resolved inference state."""
        return self.policy_for(action).preparation_inference_required

    async def list_definitions(
        self,
        context: TurnActionCatalogContext,
    ) -> list[TurnActionDefinition]:
        """Return ordered public composer definitions for one Session."""
        goal_hint = (
            TurnActionAvailabilityHint(
                state="warning",
                message=(
                    "A goal is already in progress. Manage it from the goal card."
                ),
            )
            if context.goal_in_progress
            else None
        )
        skill_snapshot = await load_skill_projection_for_actions(
            self.skill_store,
            vfs_projection_service=self.vfs_projection_service,
            agent_id=context.agent_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
            run_state=context.run_state,
            active_run_id=context.active_run_id,
        )
        return [
            TurnActionDefinition(
                id="goal",
                keyword="goal",
                label="Goal",
                description="Create a session goal.",
                message_placeholder="Describe the goal for this session.",
                action=GoalAction(),
                policy=_GOAL_POLICY,
                availability_hint=goal_hint,
                source_label=None,
                relative_hint=None,
            ),
            TurnActionDefinition(
                id="cleanup_orphan_git_worktrees",
                keyword="cleanup-worktrees",
                label="Clean up worktrees",
                description=(
                    "Remove managed Git worktrees not connected to an active session. "
                    "Local branches are preserved."
                ),
                message_placeholder="Optional cleanup note.",
                action=CleanupOrphanGitWorktreesAction(),
                policy=_CLEANUP_WORKTREES_POLICY,
                availability_hint=None,
                source_label=None,
                relative_hint=None,
            ),
            *[
                _skill_definition(item)
                for item in skill_actions_from_snapshot(skill_snapshot)
            ],
        ]

    async def prepare(
        self,
        *,
        action: TurnAction,
        context: TurnActionPreparationContext,
    ) -> TurnActionPreparationResult:
        """Prepare one typed action inside the caller transaction."""
        match action:
            case GoalAction():
                return await self._prepare_goal(context)
            case SkillAction():
                return await self._prepare_skill(context, action)
            case (
                CreateGitWorktreeAction()
                | CleanupOrphanGitWorktreesAction()
                | CreateSessionWorkingFolderAction()
                | AgentCreateGitWorktreeAction()
                | AgentRemoveGitWorktreeAction()
            ):
                return TurnActionPreparationResult(
                    events=[],
                    append_user_message=False,
                    effect=TurnActionPreparationEffect.NEUTRAL,
                    handled_failure=None,
                    operation_action=action,
                )
            case _:
                assert_never(action)

    async def _prepare_goal(
        self,
        context: TurnActionPreparationContext,
    ) -> TurnActionPreparationResult:
        objective = context.content.strip()
        if not objective:
            return _handled_failure("Goal objective is required.")
        agent_session = await self.agent_session_repository.get_by_id(
            context.session,
            context.session_id,
        )
        if agent_session is None:
            return _handled_failure("Session not found.")
        updated_at = datetime.datetime.now(datetime.UTC).isoformat()

        def mutate(current: GoalState) -> GoalState:
            if current.status in {"active", "paused", "blocked"} and current.objective:
                raise _GoalActionError("An unfinished goal already exists.")
            return GoalState(
                objective=objective,
                status="active",
                created_at=updated_at,
                updated_at=updated_at,
            )

        try:
            updated = await self.goal_store.update_in_session(
                context.session,
                agent_session.agent_id,
                context.session_id,
                mutate,
            )
        except _GoalActionError as exc:
            return _handled_failure(exc.message)
        snapshot = GoalStateSnapshot.from_state(updated)
        return TurnActionPreparationResult(
            events=[
                TurnActionPreparedEvent(
                    kind=EventKind.GOAL_UPDATED,
                    payload=_goal_updated_payload(snapshot, action="create"),
                    external_id_suffix="goal_updated",
                )
            ],
            append_user_message=True,
            effect=TurnActionPreparationEffect.ELIGIBLE,
            handled_failure=None,
            operation_action=None,
        )

    async def _prepare_skill(
        self,
        context: TurnActionPreparationContext,
        action: SkillAction,
    ) -> TurnActionPreparationResult:
        agent_session = await self.agent_session_repository.get_by_id(
            context.session,
            context.session_id,
        )
        if agent_session is None:
            return _handled_failure("Session not found.")
        item: SkillProjectionItem | None
        if action.skill_path.startswith("azents://"):
            item = None
            if (
                context.active_run_id is not None
                and self.vfs_projection_service is not None
            ):
                try:
                    resolved = await self.vfs_projection_service.resolve_file(
                        run_id=context.active_run_id,
                        agent_id=agent_session.agent_id,
                        session_id=context.session_id,
                        workspace_id=agent_session.workspace_id,
                        uri=action.skill_path,
                    )
                    item = skill_item_from_vfs_entry(resolved.entry)
                except (VfsFileResolutionError, ValueError) as exc:
                    logger.warning(
                        "Managed Skill action resolution failed",
                        extra={
                            "agent_id": agent_session.agent_id,
                            "session_id": context.session_id,
                            "run_id": context.active_run_id,
                            "skill_path": action.skill_path,
                            "error_type": type(exc).__name__,
                        },
                    )
        else:
            state = await self.skill_store.load_in_session(
                context.session,
                agent_session.agent_id,
                context.session_id,
            )
            item = resolve_active_skill(state, skill_path=action.skill_path)
        if item is None:
            return _handled_failure(
                "Selected Skill is not available in the active projection."
            )
        payload = SkillLoadedPayload(
            name=item.name,
            skill_path=item.skill_path,
            body=item.body,
            user_message=context.content,
            content_hash=item.content_hash,
            source_label=item.source_label,
            relative_hint=item.relative_hint,
        )
        return TurnActionPreparationResult(
            events=[
                TurnActionPreparedEvent(
                    kind=EventKind.SKILL_LOADED,
                    payload=_JSON_OBJECT_ADAPTER.validate_python(
                        payload.model_dump(mode="json")
                    ),
                    external_id_suffix="skill_loaded",
                )
            ],
            append_user_message=bool(context.content.strip()),
            effect=TurnActionPreparationEffect.ELIGIBLE,
            handled_failure=None,
            operation_action=None,
        )


class _GoalActionError(Exception):
    """User-visible Goal action failure."""

    def __init__(self, message: str) -> None:
        """Create one handled Goal error."""
        super().__init__(message)
        self.message = message


def _handled_failure(message: str) -> TurnActionPreparationResult:
    """Return one deterministic handled preparation failure."""
    return TurnActionPreparationResult(
        events=[],
        append_user_message=False,
        effect=TurnActionPreparationEffect.FAILED,
        handled_failure=message,
        operation_action=None,
    )


def _skill_definition(item: SkillProjectionItem) -> TurnActionDefinition:
    """Build one projection-dependent Skill action definition."""
    return TurnActionDefinition(
        id=skill_action_id(item.skill_path),
        keyword=item.slug,
        label=f"/{item.slug}",
        description=item.description,
        message_placeholder="Describe what to do with this skill.",
        action=SkillAction(skill_path=item.skill_path),
        policy=_SKILL_POLICY,
        availability_hint=None,
        source_label=item.source_label,
        relative_hint=item.relative_hint,
    )


def _goal_updated_payload(
    snapshot: GoalStateSnapshot,
    *,
    action: str,
) -> dict[str, JSONValue]:
    """Return goal_updated event payload for a Goal side effect."""
    return _JSON_OBJECT_ADAPTER.validate_python(
        {
            "sender_user_id": None,
            "content": "",
            "attachments": [],
            "metadata": {
                "source": "goal",
                "provider_slug": "goal",
                "goal_control_action": action,
                "goal_objective": snapshot.objective or "",
                "goal_status": snapshot.status or "",
                "goal_created_at": snapshot.created_at or "",
                "goal_updated_at": snapshot.updated_at or "",
            },
        }
    )


_GOAL_POLICY = TurnActionPolicy(
    action_type="goal",
    owner="goal",
    visibility="composer",
    message_policy="required",
    message_max_length=4000,
    attachment_policy="unsupported",
    admission_profile_required=True,
    preparation_inference_required=True,
    operation=False,
)
_SKILL_POLICY = TurnActionPolicy(
    action_type="skill",
    owner="skill",
    visibility="composer",
    message_policy="optional",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=True,
    preparation_inference_required=True,
    operation=False,
)
_CREATE_GIT_WORKTREE_POLICY = TurnActionPolicy(
    action_type="create_git_worktree",
    owner="workspace",
    visibility="direct",
    message_policy="optional",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=True,
    preparation_inference_required=False,
    operation=True,
)
_CLEANUP_WORKTREES_POLICY = TurnActionPolicy(
    action_type="cleanup_orphan_git_worktrees",
    owner="workspace",
    visibility="composer",
    message_policy="optional",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=True,
    preparation_inference_required=False,
    operation=True,
)
_CREATE_SESSION_WORKING_FOLDER_POLICY = TurnActionPolicy(
    action_type="create_session_working_folder",
    owner="workspace",
    visibility="internal",
    message_policy="none",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=False,
    preparation_inference_required=False,
    operation=True,
)
_AGENT_CREATE_GIT_WORKTREE_POLICY = TurnActionPolicy(
    action_type="agent_create_git_worktree",
    owner="workspace",
    visibility="internal",
    message_policy="none",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=False,
    preparation_inference_required=False,
    operation=True,
)
_AGENT_REMOVE_GIT_WORKTREE_POLICY = TurnActionPolicy(
    action_type="agent_remove_git_worktree",
    owner="workspace",
    visibility="internal",
    message_policy="none",
    message_max_length=None,
    attachment_policy="unsupported",
    admission_profile_required=False,
    preparation_inference_required=False,
    operation=True,
)
