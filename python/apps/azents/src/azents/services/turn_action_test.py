"""TurnAction capability registry tests."""

from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState
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
from azents.engine.tools.goal import GoalStateStore
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionSnapshot,
    SkillProjectionState,
    SkillStateStore,
)
from azents.repos.agent_session import AgentSessionRepository

from .turn_action import (
    TurnActionAdmissionError,
    TurnActionCapabilityRegistry,
    TurnActionCatalogContext,
    TurnActionPreparationContext,
    TurnActionPreparationEffect,
)

_PROFILE = RequestedInferenceProfile(
    model_target_label="default",
    reasoning_effort=None,
)


class _SkillStore:
    """Skill projection store test double."""

    def __init__(self, state: SkillProjectionState | None = None) -> None:
        self.state = state or SkillProjectionState()

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Return the configured projection."""
        del agent_id, session_id
        return self.state


def _registry(
    skill_store: _SkillStore | None = None,
) -> TurnActionCapabilityRegistry:
    """Create a registry whose stateful dependencies are not used by policy tests."""
    return TurnActionCapabilityRegistry(
        agent_session_repository=cast(AgentSessionRepository, object()),
        goal_store=cast(GoalStateStore, object()),
        skill_store=cast(SkillStateStore, skill_store or _SkillStore()),
        vfs_projection_service=None,
    )


def _agent_create_action() -> AgentCreateGitWorktreeAction:
    return AgentCreateGitWorktreeAction(
        bridge_identity="bridge-create",
        originating_run_id="run-origin",
        client_tool_call_id="call-create",
        session_agent_context_id="context-1",
        originating_agent_session_id="session-1",
        source_project_id="project-1",
        source_project_path="/workspace/agent/source",
        starting_ref=None,
        branch_name=None,
    )


def _agent_remove_action() -> AgentRemoveGitWorktreeAction:
    return AgentRemoveGitWorktreeAction(
        bridge_identity="bridge-remove",
        originating_run_id="run-origin",
        client_tool_call_id="call-remove",
        session_agent_context_id="context-1",
        originating_agent_session_id="session-1",
        worktree_project_id="project-2",
        worktree_allocation_id="allocation-1",
        worktree_path="/workspace/agent/worktree",
        force=False,
    )


@pytest.mark.parametrize(
    ("action", "visibility", "inference_required", "operation"),
    [
        (GoalAction(), "composer", True, False),
        (SkillAction(skill_path="/skills/review/SKILL.md"), "composer", True, False),
        (
            CreateGitWorktreeAction(
                source_project_path="/workspace/agent/source",
                starting_ref="main",
            ),
            "direct",
            False,
            True,
        ),
        (CleanupOrphanGitWorktreesAction(), "composer", False, True),
        (CreateSessionWorkingFolderAction(), "internal", False, True),
        (_agent_create_action(), "internal", False, True),
        (_agent_remove_action(), "internal", False, True),
    ],
)
def test_policy_covers_every_turn_action(
    action: TurnAction,
    visibility: str,
    inference_required: bool,
    operation: bool,
) -> None:
    """Every closed action discriminator resolves one complete shared policy."""
    policy = _registry().policy_for(action)

    assert policy.action_type == action.type
    assert policy.visibility == visibility
    assert policy.preparation_inference_required is inference_required
    assert policy.operation is operation


@pytest.mark.parametrize(
    "action",
    [
        GoalAction(),
        SkillAction(skill_path="/skills/review/SKILL.md"),
        CreateGitWorktreeAction(
            source_project_path="/workspace/agent/source",
            starting_ref="main",
        ),
        CleanupOrphanGitWorktreesAction(),
    ],
)
def test_public_admission_uses_shared_policy(action: PublicTurnAction) -> None:
    """Public actions share profile and attachment admission behavior."""
    registry = _registry()

    assert (
        registry.validate_public_input(
            action=action,
            message="objective" if isinstance(action, GoalAction) else "",
            attachments=None,
            inference_profile=_PROFILE,
        )
        == _PROFILE
    )
    with pytest.raises(
        TurnActionAdmissionError,
        match="Run-producing input requires an inference profile",
    ):
        registry.validate_public_input(
            action=action,
            message="objective" if isinstance(action, GoalAction) else "",
            attachments=None,
            inference_profile=None,
        )
    with pytest.raises(
        TurnActionAdmissionError,
        match="does not support attachments",
    ):
        registry.validate_public_input(
            action=action,
            message="objective" if isinstance(action, GoalAction) else "",
            attachments=["exchange://file"],
            inference_profile=_PROFILE,
        )


def test_goal_admission_enforces_objective_and_maximum_length() -> None:
    """Goal validation preserves the composer contract."""
    registry = _registry()

    with pytest.raises(TurnActionAdmissionError, match="Goal objective is required"):
        registry.validate_public_input(
            action=GoalAction(),
            message=" ",
            attachments=None,
            inference_profile=_PROFILE,
        )
    with pytest.raises(TurnActionAdmissionError, match="4000 characters or fewer"):
        registry.validate_public_input(
            action=GoalAction(),
            message="x" * 4001,
            attachments=None,
            inference_profile=_PROFILE,
        )


def test_decode_rejects_non_turn_and_unknown_actions() -> None:
    """Persisted decoding does not admit actions outside the closed TurnAction set."""
    registry = _registry()

    with pytest.raises(ValidationError):
        registry.decode({"type": "command", "name": "compact"})
    with pytest.raises(ValidationError):
        registry.decode({"type": "future_action"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        CreateGitWorktreeAction(
            source_project_path="/workspace/agent/source",
            starting_ref="main",
        ),
        CleanupOrphanGitWorktreesAction(),
        CreateSessionWorkingFolderAction(),
        _agent_create_action(),
        _agent_remove_action(),
    ],
)
async def test_operation_preparation_returns_neutral_handoff(
    action: OperationAction,
) -> None:
    """Operation actions remain neutral until the Worker executor boundary."""
    prepared = await _registry().prepare(
        action=action,
        context=TurnActionPreparationContext(
            session=cast(AsyncSession, object()),
            session_id="session-1",
            active_run_id="run-1",
            mailbox_item_id="mailbox-1",
            content="",
        ),
    )

    assert prepared.events == []
    assert prepared.append_user_message is False
    assert prepared.effect is TurnActionPreparationEffect.NEUTRAL
    assert prepared.handled_failure is None
    assert prepared.operation_action == action


@pytest.mark.asyncio
async def test_catalog_combines_static_and_projection_owned_definitions() -> None:
    """Catalog discovery preserves ordering, policy, hints, and Skill metadata."""
    skill = SkillProjectionItem(
        id="skill-1",
        source_kind="project_claude",
        project_id="project-1",
        project_path="/workspace/agent/project",
        skill_dir_path="/workspace/agent/project/.claude/skills/review",
        skill_path="/workspace/agent/project/.claude/skills/review/SKILL.md",
        slug="review",
        name="Review",
        description="Review code.",
        body="Skill body",
        content_hash="hash",
        source_label="project",
        relative_hint=".claude/skills/review",
    )
    registry = _registry(
        _SkillStore(
            SkillProjectionState(
                latest=SkillProjectionSnapshot(items=[skill]),
                active=SkillProjectionSnapshot(),
            )
        )
    )

    definitions = await registry.list_definitions(
        TurnActionCatalogContext(
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_state=AgentSessionRunState.IDLE,
            active_run_id=None,
            goal_in_progress=True,
        )
    )

    assert [definition.action.type for definition in definitions] == [
        "goal",
        "cleanup_orphan_git_worktrees",
        "skill",
    ]
    assert definitions[0].availability_hint is not None
    assert definitions[0].policy.message_max_length == 4000
    assert definitions[1].policy.operation is True
    assert definitions[2].source_label == "project"
    assert definitions[2].relative_hint == ".claude/skills/review"
