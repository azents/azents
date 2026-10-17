"""Final executor and later Runtime export use current exact personal admission."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import BaseModel

from azents.core.enums import AgentRuntimeCapability
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.personal_toolkit_runtime import ToolkitEffectAdmission
from azents.core.runtime_capabilities import RuntimeCapabilityResolver
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.core.tools import (
    GitHubToolkitConfig,
    ResolveContext,
    Toolkit,
    ToolkitContext,
    ToolkitExecutionMode,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.tool_invocation import PreparedClientToolInvocation
from azents.engine.events.tools import (
    ToolCatalogClientToolInvoker,
    build_tool_catalog,
    project_tool_catalog_for_client_compatibility,
)
from azents.engine.run.client_tool_compatibility import ClientToolAdapterProfile
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.resolve import resolve_agent_tools
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolSpec,
    FunctionToolWireVariant,
)
from azents.engine.tooling.personal_admission import PersonalToolkitAdmission
from azents.engine.tools.builtin import _collect_secret_env
from azents.engine.tools.github import GitHubToolkit
from azents.repos.engine_resolve import EngineResolveRepositories
from azents.repos.toolkit.personal_runtime_test import Harness, Root
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- shared committed PostgreSQL fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- actual canonical root and source repository
)
from azents.repos.toolkit.personal_test import creation
from azents.runtime.types import RuntimeDomainConfig


class SourceConfig(BaseModel):
    """Local validated configuration for the controlled Provider."""


class EffectToolkit(Toolkit[SourceConfig]):
    """Controlled external boundary with real current database admission."""

    def __init__(
        self,
        admission: ToolkitEffectAdmission | None,
        token: str | None,
        on_call: Callable[[], Awaitable[None]] | None,
        on_export: Callable[[], Awaitable[None]] | None,
    ) -> None:
        self.effect_admission = admission
        self.token = token
        self.on_call = on_call
        self.on_export = on_export
        self.calls: list[str] = []
        self.exports = 0
        self.cancelled = asyncio.Event()

    async def __call__(self, arguments: str) -> str:
        self.calls.append(arguments)
        if self.on_call is not None:
            await self.on_call()
        return "fixture external result"

    async def execute_plaintext_custom(self, arguments: str) -> str:
        return await self(arguments)

    async def cancel(self, request: FunctionToolCancelRequest) -> None:
        del request
        self.cancelled.set()

    async def expose_env(self) -> dict[str, str]:
        if self.token is None:
            return {}
        if self.effect_admission is not None:
            await self.effect_admission.assert_current()
        self.exports += 1
        if self.on_export is not None:
            await self.on_export()
        return {"GH_TOKEN": self.token}

    async def update_context(self, context: TurnContext) -> ToolkitState:
        del context
        return ToolkitState(
            ToolkitStatus.ENABLED,
            [
                FunctionTool(
                    spec=FunctionToolSpec(
                        name="send",
                        description="Send once",
                        input_schema={"type": "object"},
                    ),
                    handler=self,
                    cancel_handler=self.cancel,
                    wire_variants=(
                        FunctionToolWireVariant("json_function", None),
                        FunctionToolWireVariant("plaintext_custom", None),
                    ),
                )
            ],
        )


async def restrict(h: Harness, root: Root, toolkit_id: str) -> None:
    await h.foundation.operations.mutate_access(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        mutations=[
            PersonalToolkitAccessMutation(
                toolkit_id, None, frozenset(), frozenset([root.agent_id]), Mode.ALL
            )
        ],
    )


@pytest.mark.parametrize("wire", ["json_function", "plaintext_custom"])
@pytest.mark.parametrize("already_admitted", [True, False])
async def test_final_catalog_handler_guard_survives_wire_projection_and_withdrawal(
    runtime: Harness,
    wire: ClientToolWireDialect,
    already_admitted: bool,
) -> None:
    h = runtime
    f = h.foundation
    saved = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    guard = PersonalToolkitAdmission(h.repository, source.target)
    entered, release = asyncio.Event(), asyncio.Event()

    async def external_call() -> None:
        entered.set()
        await release.wait()

    personal = EffectToolkit(
        guard,
        "fixture-personal-token",
        external_call if already_admitted else None,
        None,
    )
    shared = EffectToolkit(None, "fixture-shared-token", None, None)
    candidate = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                personal,
                source.namespace,
                source.toolkit.slug,
                True,
                "mcp",
                saved.id,
                str(saved.revision),
                True,
            ),
            ToolkitBinding(
                shared, "shared", "personal", True, "mcp", "shared-fixture", "1", True
            ),
        ],
        context=TurnContext(
            workspace_id=root.workspace_id,
            model="fixture",
            run_id="fixture",
            publish_event=AsyncMock(),
        ),
    )
    catalog = project_tool_catalog_for_client_compatibility(
        candidate,
        frozenset(),
        ClientToolAdapterProfile(
            "fixture",
            None,
            "fixture",
            "fixture",
            (wire,),
            (),
        ),
    )
    name = f"{source.namespace}__send"
    assert catalog.effect_admissions[name] is guard
    assert catalog.tools[name].handler is personal
    assert catalog.entries[name].source.toolkit_config_id == saved.id
    invoker = ToolCatalogClientToolInvoker(catalog)
    call = PreparedClientToolInvocation("fixture-call", name, "{}", wire)
    if already_admitted:
        task = asyncio.create_task(invoker.invoke(call))
        await entered.wait()
        await restrict(h, root, saved.id)
        release.set()
        assert (await task).status == "completed"
    else:
        await restrict(h, root, saved.id)
    denied = await invoker.invoke(call)
    assert denied.status == "failed" and not denied.execution_succeeded
    assert denied.metadata["kind"] == "personal_toolkit_authorization_unavailable"
    assert len(personal.calls) == (1 if already_admitted else 0)
    assert shared.calls == []
    # Cleanup for an admitted operation is not a new protected external call.
    invoker.request_cancel(call)
    await personal.cancelled.wait()
    still_shared = await invoker.invoke(
        PreparedClientToolInvocation("shared-call", "shared__send", "{}", wire)
    )
    assert still_shared.status == "completed" and shared.calls == ["{}"]


@pytest.mark.parametrize("during_export", [True, False])
async def test_runtime_export_repeats_admission_before_and_after_credential_gap(
    runtime: Harness,
    during_export: bool,
) -> None:
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation(),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)

    async def withdraw() -> None:
        await restrict(h, root, saved.id)

    personal = EffectToolkit(
        PersonalToolkitAdmission(h.repository, source.target),
        "fixture-private-token",
        None,
        withdraw if during_export else None,
    )
    if not during_export:
        await withdraw()
    with pytest.raises(FunctionToolError) as denied:
        await _collect_secret_env([personal], root.agent_id)
    assert denied.value.metadata["kind"] == "personal_toolkit_authorization_unavailable"
    assert personal.exports == (1 if during_export else 0)
    assert "fixture-private-token" not in str(denied.value)


async def test_mixed_environment_retains_common_last_source_wins_merge(
    runtime: Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = runtime
    await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation(),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)
    personal = EffectToolkit(
        PersonalToolkitAdmission(h.repository, source.target),
        "fixture-personal",
        None,
        None,
    )
    shared = EffectToolkit(None, "fixture-shared", None, None)
    assert await _collect_secret_env([shared, personal], root.agent_id) == {
        "GH_TOKEN": "fixture-personal"
    }
    assert await _collect_secret_env([personal, shared], root.agent_id) == {
        "GH_TOKEN": "fixture-shared"
    }
    assert any(
        record.__dict__.get("var_name") == "GH_TOKEN" for record in caplog.records
    )
    assert "fixture-personal" not in caplog.text and "fixture-shared" not in caplog.text


async def test_other_workspace_target_cannot_dispatch_or_export_personal_credentials(
    runtime: Harness,
) -> None:
    """Same account and stale source metadata do not authorize another workload."""
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation(),
    )
    root_a = await h.root(h.foundation.user_id, 0)
    root_b = await h.root(h.foundation.user_id, 2)
    [source] = await h.sources(root_a)
    target = dataclasses.replace(
        source.target,
        execution_owner=root_b.owner,
        workspace_id=root_b.workspace_id,
        agent_id=root_b.agent_id,
        root_session_id=root_b.owner.session_id,
    )
    personal = EffectToolkit(
        PersonalToolkitAdmission(h.repository, target),
        "fixture-cross-workspace-secret",
        None,
        None,
    )
    catalog = await build_tool_catalog(
        toolkit_bindings=[
            ToolkitBinding(
                personal,
                source.namespace,
                source.toolkit.slug,
                True,
                "mcp",
                saved.id,
                str(saved.revision),
                True,
            )
        ],
        context=TurnContext(
            workspace_id=root_b.workspace_id,
            model="fixture",
            run_id="fixture",
            publish_event=AsyncMock(),
        ),
    )
    result = await ToolCatalogClientToolInvoker(catalog).invoke(
        PreparedClientToolInvocation(
            "foreign-source", f"{source.namespace}__send", "{}", "json_function"
        )
    )
    assert result.status == "failed" and not result.execution_succeeded
    assert personal.calls == []
    with pytest.raises(FunctionToolError) as denied:
        await _collect_secret_env([personal], root_b.agent_id)
    assert personal.exports == 0
    assert "fixture-cross-workspace-secret" not in str(denied.value)


@pytest.mark.parametrize("inject", [True, False])
async def test_real_github_disabled_export_does_not_gate_unrelated_runtime(
    runtime: Harness,
    inject: bool,
) -> None:
    h = runtime
    config = GitHubToolkitConfig(
        github_auth_type="pat", inject_runtime_environment=inject
    )
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation().model_copy(
            update={
                "toolkit_type": "github",
                "config": config.model_dump(),
                "credentials": '{"type":"pat","token":"fixture-owner-token"}',
            }
        ),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)
    token = AsyncMock(return_value="fixture-owner-token")
    github = GitHubToolkit(config=config, runtime_environment_token_provider=token)
    github.effect_admission = PersonalToolkitAdmission(h.repository, source.target)
    await restrict(h, root, saved.id)
    if inject:
        with pytest.raises(FunctionToolError):
            await _collect_secret_env([github], root.agent_id)
    else:
        shared = EffectToolkit(None, "fixture-shared", None, None)
        assert await _collect_secret_env([github, shared], root.agent_id) == {
            "GH_TOKEN": "fixture-shared"
        }
    token.assert_not_awaited()


class SourceProvider(ToolkitProvider[SourceConfig]):
    """Exercise actual Engine resolution with a controlled Provider boundary."""

    slug: ClassVar[str] = "mcp"
    name: ClassVar[str] = "Fixture"
    description: ClassVar[str] = "Fixture"
    system_prompt: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = SourceConfig

    def __init__(self) -> None:
        self.contexts: list[ResolveContext] = []

    async def resolve(
        self, config: SourceConfig, context: ResolveContext
    ) -> Toolkit[SourceConfig]:
        del config
        self.contexts.append(context)
        return EffectToolkit(context.effect_admission, "fixture-token", None, None)


@pytest.mark.parametrize("root_kind", ["user", "team", "other_user"])
async def test_engine_resolves_personal_sources_only_from_exact_durable_root(
    runtime: Harness,
    root_kind: str,
) -> None:
    h = runtime
    f = h.foundation
    saved = await f.operations.create(
        user_id=f.user_id, workspace_id=f.workspace_ids[0], create=creation()
    )
    root = await h.root(
        f.user_id
        if root_kind == "user"
        else None
        if root_kind == "team"
        else f.other_user_id,
        0,
    )
    shared_read = Mock()
    shared_read.list_effective_for_agent = AsyncMock(return_value=[])
    repositories = EngineResolveRepositories(
        invoke_read=Mock(),
        model_read=Mock(),
        toolkit_read=shared_read,
        personal_toolkits=h.repository,
        chatgpt_oauth=Mock(),
        xai_oauth=Mock(),
        kimi_oauth=Mock(),
    )
    provider = SourceProvider()
    context = ToolkitContext(
        root.owner.session_id,
        root.workspace_id,
        root.agent_id,
        "fixture-run",
        AsyncMock(),
    )
    bindings = await resolve_agent_tools(
        root.agent_id,
        context,
        execution_owner=root.owner,
        execution_mode=ToolkitExecutionMode.ROOT,
        toolkit_registry={"mcp": provider},
        repositories=repositories,
        web_url="https://app.test",
        oauth_secret_key=None,
        mcp_proxy_url=None,
        runtime_domain_config=RuntimeDomainConfig(
            allowed_domains=(), denied_domains=()
        ),
        workspace_handle="fixture-workload",
        memory_enabled=False,
        runtime_capability_resolver=RuntimeCapabilityResolver.from_agent(
            state=AgentRuntimeCapability.NONE, version=1
        ),
    )
    if root_kind != "user":
        assert bindings == [] and provider.contexts == []
        return
    [binding] = bindings
    [resolved_context] = provider.contexts
    assert binding.toolkit_config_id == saved.id
    assert binding.toolkit.effect_admission is resolved_context.effect_admission
    assert resolved_context.effect_admission is not None
    assert resolved_context.effect_admission.target.execution_owner == root.owner
    assert resolved_context.workspace_id == root.workspace_id
    assert {field.name for field in dataclasses.fields(ResolveContext)}.isdisjoint(
        {"user_id", "owner_user_id"}
    )


async def test_engine_rejects_mixed_session_owner_before_source_lookup(
    runtime: Harness,
) -> None:
    h = runtime
    root = await h.root(h.foundation.user_id, 0)
    shared_read = Mock()
    shared_read.list_effective_for_agent = AsyncMock(return_value=[])
    repositories = EngineResolveRepositories(
        invoke_read=Mock(),
        model_read=Mock(),
        toolkit_read=shared_read,
        personal_toolkits=h.repository,
        chatgpt_oauth=Mock(),
        xai_oauth=Mock(),
        kimi_oauth=Mock(),
    )
    with pytest.raises(ValueError, match="workload"):
        await resolve_agent_tools(
            root.agent_id,
            ToolkitContext(
                "different-session",
                root.workspace_id,
                root.agent_id,
                "fixture",
                AsyncMock(),
            ),
            execution_owner=root.owner,
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            repositories=repositories,
            web_url=None,
            oauth_secret_key=None,
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(), denied_domains=()
            ),
            workspace_handle=None,
            memory_enabled=False,
            runtime_capability_resolver=RuntimeCapabilityResolver.from_agent(
                state=AgentRuntimeCapability.NONE, version=1
            ),
        )
    shared_read.list_effective_for_agent.assert_not_awaited()
