"""Packaged Browser Skill projection, load and executable example contracts."""

import json
import re
from typing import Literal, assert_never

import frontmatter
import pytest
from azents_runtime_control.browser_contract import (
    BrowserAuthority,
    BrowserObserveCommand,
    BrowserOpenCommand,
    encode_browser_command,
)
from pydantic import BaseModel, ConfigDict, JsonValue

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.core.skill_projection import SkillProjectionState
from azents.core.tools import TurnContext
from azents.core.vfs import VfsProjection, make_vfs_projection
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.tools.browser import (
    BrowserActInput,
    BrowserObserveInput,
    BrowserOpenInput,
    _act_command,
    _observe_target,
)
from azents.engine.tools.browser_test import _Harness
from azents.engine.tools.skill import SkillToolkit, skill_items_from_vfs_projection
from azents.engine.tools.skill_test import (
    _managed_runtime_capability_resolver,
    _noop_publish_event,
    _SkillStore,
    _VfsService,
)
from azents.services.vfs import GLOBAL_RELEASE_SOURCE, ReleaseVfsCatalog

_ROOT = "azents://skills/azents/browser/"


class _Example(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["browser_open", "browser_observe", "browser_act"]
    arguments: dict[str, JsonValue]


@pytest.fixture
async def projection() -> VfsProjection:
    snapshot = await ReleaseVfsCatalog().snapshot([GLOBAL_RELEASE_SOURCE])
    assert not snapshot.diagnostics
    return make_vfs_projection(snapshot.revisions)


async def test_release_browser_package_is_discoverable_and_loads_from_projection(
    projection: VfsProjection,
) -> None:
    items = skill_items_from_vfs_projection(projection)
    [browser] = [item for item in items if item.skill_path == _ROOT + "SKILL.md"]
    entry = projection.find(browser.skill_path)
    assert entry is not None
    saved = entry.decode_body().decode("utf-8")
    parsed = frontmatter.loads(saved)
    assert parsed["name"] == "browser"
    assert isinstance(parsed["description"], str) and parsed["description"].strip()
    for relative in re.findall(r"\]\((references/[^)]+)\)", saved):
        reference = projection.find(_ROOT + relative)
        assert reference is not None and reference.decode_body().decode("utf-8")

    service = _VfsService(projection)
    toolkit = SkillToolkit(
        store=_SkillStore(SkillProjectionState()),
        projection_service=None,
        vfs_projection_service=service,
        agent_id="agent-1",
        session_id="session-1",
    )
    toolkit.set_runtime_capability_resolver(_managed_runtime_capability_resolver())
    context = TurnContext(
        workspace_id="workspace-1",
        model="test-model",
        run_id="run-1",
        publish_event=_noop_publish_event,
    )
    assert browser.skill_path in await toolkit.get_static_prompt(context)
    state = await toolkit.update_context(context)
    [load] = state.tools
    loaded = await load.handler(json.dumps({"skill_path": browser.skill_path}))
    assert isinstance(loaded, str) and browser.body in loaded
    assert projection.revision_id in loaded
    assert service.resolve_calls[-1]["run_id"] == "run-1"
    assert service.resolve_calls[-1]["workspace_id"] == "workspace-1"


async def test_confidential_script_and_guidance_are_current_run_resources(
    projection: VfsProjection,
) -> None:
    script = projection.find(_ROOT + "scripts/encrypt.py")
    guide = projection.find(_ROOT + "references/confidential-input.md")
    assert script is not None and guide is not None
    source = script.decode_body().decode("utf-8")
    guidance = guide.decode_body().decode("utf-8")
    assert 'dependencies = ["PyNaCl==1.6.2"]' in source
    assert "--env" in source and "AZENTS_BROWSER_INPUT_PUBLIC_KEY" in source
    assert "import_file" in guidance and "write_stdin" in guidance
    assert "uv run --no-project --script" in guidance
    assert "encrypted_text" in guidance


@pytest.mark.parametrize("provider", list(LLMProvider))
async def test_browser_skill_examples_match_final_tools_and_provider_lowering(
    projection: VfsProjection, provider: LLMProvider
) -> None:
    tools = _Harness().tools()
    declarations: list[dict[str, object]] = [
        {
            "type": "function",
            "name": tool.spec.name,
            "description": tool.spec.description,
            "parameters": tool.spec.input_schema,
        }
        for tool in tools.values()
    ]
    capabilities = ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(supported=True)
    )
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        native = OpenAIResponsesLowerer(
            provider=provider.value,
            provider_id=provider,
            model="fixture",
            tools=declarations,
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            top_k=None,
        ).lower([], model="fixture", native_replay_context=None)
        schemas = {}
        for definition in native.tools:
            parameters = definition["parameters"]
            assert isinstance(parameters, dict)
            schemas[definition["name"]] = parameters
    else:
        native_pydantic = PydanticAILowerer(
            provider=provider.value,
            provider_id=provider,
            model="fixture",
            tools=declarations,
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            top_k=None,
        ).lower([], model="fixture", native_replay_context=None)
        schemas = {
            definition.name: definition.parameters_json_schema
            for definition in native_pydantic.parameters.function_tools
        }
    authority = BrowserAuthority("current-session", "/current/runtime/session")
    seen = set()
    for entry in projection.entries:
        if not entry.canonical_uri.startswith(_ROOT + "references/"):
            continue
        for raw in re.findall(
            r"```json\n(.*?)\n```", entry.decode_body().decode("utf-8"), re.DOTALL
        ):
            example = _Example.model_validate_json(raw)
            seen.add(example.tool)
            match example.tool:
                case "browser_open":
                    args = BrowserOpenInput.model_validate(example.arguments)
                    command = BrowserOpenCommand(
                        authority, args.task_id, args.url, args.label
                    )
                    normalized = args.model_dump(mode="json")
                case "browser_observe":
                    observation = BrowserObserveInput.model_validate(example.arguments)
                    command = BrowserObserveCommand(
                        authority,
                        _observe_target(observation),
                        observation.view,
                        observation.capture_full_page,
                        observation.max_characters,
                    )
                    normalized = observation.model_dump(mode="json")
                case "browser_act":
                    action = BrowserActInput.model_validate(example.arguments)
                    command = _act_command(action, authority)
                    normalized = action.model_dump(mode="json")
                case _:
                    assert_never(example.tool)
            encode_browser_command(command)
            properties = schemas[example.tool]["properties"]
            assert isinstance(properties, dict)
            assert set(normalized) <= set(properties)
    assert seen == set(tools)
