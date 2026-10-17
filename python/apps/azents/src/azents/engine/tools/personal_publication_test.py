"""Personal discovery publication repeats admission inside the write transaction."""

import dataclasses

import pytest

from azents.core.engine_tool_state import McpToolSnapshotItem, McpToolSnapshotState
from azents.core.personal_toolkit_runtime import PersonalToolkitExecutionTarget
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.personal_admission import (
    PersonalToolkitAdmission,
    publish_tool_snapshot,
)
from azents.engine.tools.personal_mcp_test import restrict
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.toolkit.personal_runtime import PersonalToolkitRuntimeRepository
from azents.repos.toolkit.personal_runtime_test import Harness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- committed PostgreSQL fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- canonical root/current source
)
from azents.repos.toolkit.personal_test import creation


@pytest.mark.parametrize("timing", ["before", "preflight_gap", "none"])
async def test_personal_snapshot_publication_rechecks_inside_parent_transaction(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    timing: str,
) -> None:
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation(),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)
    store = EngineMcpSnapshotFactory(h.foundation.writes, h.foundation.writes).create(
        agent_id=root.agent_id,
        session_id=root.owner.session_id,
        toolkit_namespace="mcp",
        state_name="personal-publication",
    )
    assert store is not None
    old = McpToolSnapshotState(server_url="https://mcp.test", tools=[])
    await store.replace(old)
    new = McpToolSnapshotState(
        server_url="https://mcp.test",
        tools=[
            McpToolSnapshotItem(
                raw_name="send",
                model_name="send",
                description="Send",
                input_schema={"type": "object"},
                server_url="https://mcp.test",
                use_streamable_http=True,
            )
        ],
    )
    if timing == "before":
        await restrict(h, root, saved.id)
    elif timing == "preflight_gap":
        original = PersonalToolkitRuntimeRepository.admit

        async def preflight(
            repository: PersonalToolkitRuntimeRepository,
            target: PersonalToolkitExecutionTarget,
        ) -> None:
            await original(repository, target)
            await restrict(h, root, saved.id)

        monkeypatch.setattr(PersonalToolkitRuntimeRepository, "admit", preflight)
    if timing == "none":
        await publish_tool_snapshot(
            store=store,
            snapshot=new,
            admission=PersonalToolkitAdmission(h.repository, source.target),
        )
        assert await store.load() == new
        mismatched = dataclasses.replace(store, agent_id="foreign-agent")
        with pytest.raises(ValueError, match="identity"):
            await mismatched.replace_personal(
                new, repository=h.repository, target=source.target
            )
    else:
        with pytest.raises(FunctionToolError):
            await publish_tool_snapshot(
                store=store,
                snapshot=new,
                admission=PersonalToolkitAdmission(h.repository, source.target),
            )
        assert await store.load() == old
