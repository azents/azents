"""testenv-only runtime hook QA toolkit."""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from azents.core.tools import (
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    RunEndHookContext,
    RunStartHookContext,
    RuntimeHibernateHookContext,
    RuntimeHooks,
    RuntimeRestoreHookContext,
    SessionStartHookContext,
    ToolCallDecision,
    ToolCallDeny,
    ToolOutputDecision,
    ToolOutputReplace,
    TurnEndHookContext,
    TurnInjectedPrompt,
    TurnStartHookContext,
    TurnStartResult,
)
from azents.engine.run.types import FunctionTool
from azents.engine.tooling.make_tool import make_tool

logger = logging.getLogger(__name__)


class TestenvRuntimeHookQAConfig(BaseModel):
    """testenv runtime hook QA settings."""

    mode: Literal["observe", "deny", "replace"] = "observe"
    visible_prompt: str | None = None
    hidden_prompt: str | None = None
    deny_message: str = "Runtime hook QA denied this tool call."
    replacement_output: str = "Runtime hook QA replaced the tool output."
    sensitive_marker: str = "RUNTIME_HOOK_QA_SECRET_SHOULD_NOT_APPEAR"
    delay_seconds: float = 0.0
    release_file_path: str | None = None


class RuntimeHookQAProbeInput(BaseModel):
    """runtime_hook_qa_probe tool input."""

    marker: str = Field(description="QA marker to include in the raw tool output")


class TestenvRuntimeHookQAToolkit(Toolkit[TestenvRuntimeHookQAConfig]):
    """testenv toolkit that observes runtime hook QA scenarios through product path."""

    def __init__(self, config: TestenvRuntimeHookQAConfig) -> None:
        self._config = config

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Enable QA probe tool."""
        del context
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[self._make_probe_tool()],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static QA toolkit prompt for the current run."""
        del context
        return "Runtime hook QA toolkit is active."

    def hooks(self) -> RuntimeHooks:
        """Return lifecycle hook mapping targeted by QA."""
        return {
            "on_session_start": self._on_session_start,
            "on_run_start": self._on_run_start,
            "on_run_end": self._on_run_end,
            "on_turn_start": self._on_turn_start,
            "on_turn_end": self._on_turn_end,
            "on_before_tool_call": self._on_before_tool_call,
            "on_after_tool_call": self._on_after_tool_call,
            "on_runtime_hibernate": self._on_runtime_hibernate,
            "on_runtime_restore": self._on_runtime_restore,
        }

    def _make_probe_tool(self) -> FunctionTool:
        """Create QA probe tool."""

        async def runtime_hook_qa_probe(input: RuntimeHookQAProbeInput) -> str:
            """Return deterministic runtime hook QA marker."""
            logger.info(
                "Runtime hook QA probe executed",
                extra={"qa_marker": input.marker},
            )
            if self._config.release_file_path is not None:
                release_file = Path(self._config.release_file_path)
                logger.info(
                    "Runtime hook QA probe waiting for release file",
                    extra={"release_file_path": str(release_file)},
                )
                while not release_file.exists():
                    await asyncio.sleep(0.1)
            if self._config.delay_seconds > 0:
                await asyncio.sleep(self._config.delay_seconds)
            return f"runtime hook qa raw output: {input.marker}"

        return make_tool(
            runtime_hook_qa_probe,
            name="runtime_hook_qa_probe",
            description="Return a deterministic runtime hook QA marker.",
        )

    async def _on_session_start(self, context: SessionStartHookContext) -> None:
        self._log("on_session_start", context)

    async def _on_run_start(self, context: RunStartHookContext) -> None:
        self._log("on_run_start", context)

    async def _on_run_end(self, context: RunEndHookContext) -> None:
        self._log("on_run_end", context)

    async def _on_turn_start(self, context: TurnStartHookContext) -> TurnStartResult:
        self._log("on_turn_start", context)
        prompts: list[TurnInjectedPrompt] = []
        if self._config.visible_prompt is not None:
            prompts.append(
                TurnInjectedPrompt(
                    persistence="visible_user_input",
                    text=self._config.visible_prompt,
                )
            )
        if self._config.hidden_prompt is not None:
            prompts.append(
                TurnInjectedPrompt(
                    persistence="hidden_internal_input",
                    text=self._config.hidden_prompt,
                )
            )
        return TurnStartResult(injected_prompts=prompts)

    async def _on_turn_end(self, context: TurnEndHookContext) -> None:
        self._log("on_turn_end", context)

    async def _on_before_tool_call(
        self, context: BeforeToolCallHookContext
    ) -> ToolCallDecision | None:
        self._log("on_before_tool_call", context)
        if self._config.mode == "deny" and context.tool_name.endswith(
            "runtime_hook_qa_probe"
        ):
            return ToolCallDeny(message=self._config.deny_message)
        return None

    async def _on_after_tool_call(
        self, context: AfterToolCallHookContext
    ) -> ToolOutputDecision | None:
        self._log("on_after_tool_call", context)
        if self._config.mode == "replace" and context.tool_name.endswith(
            "runtime_hook_qa_probe"
        ):
            return ToolOutputReplace(output_text=self._config.replacement_output)
        return None

    async def _on_runtime_hibernate(self, context: RuntimeHibernateHookContext) -> None:
        self._log("on_runtime_hibernate", context)

    async def _on_runtime_restore(self, context: RuntimeRestoreHookContext) -> None:
        self._log("on_runtime_restore", context)

    def _log(self, lifecycle: str, context: object) -> None:
        """Leave QA lifecycle event without sensitive payload."""
        logger.info(
            "Runtime hook QA lifecycle event: %s",
            lifecycle,
            extra={
                "runtime_hook_qa_lifecycle": lifecycle,
                "workspace_id": getattr(context, "workspace_id", None),
                "agent_id": getattr(context, "agent_id", None),
                "session_id": getattr(context, "session_id", None),
                "run_id": getattr(context, "run_id", None),
                "reason": getattr(context, "reason", None),
                "tool_name": getattr(context, "tool_name", None),
            },
        )


class TestenvRuntimeHookQAProvider(ToolkitProvider[TestenvRuntimeHookQAConfig]):
    """runtime hook QA provider registered only in testenv."""

    slug = "runtime_hook_qa"
    name = "Runtime Hook QA"
    description = "Testenv-only runtime hook QA toolkit"
    system_prompt = "Runtime hook QA toolkit for deterministic testenv scenarios."
    config_model = TestenvRuntimeHookQAConfig

    async def resolve(
        self,
        config: TestenvRuntimeHookQAConfig,
        context: ResolveContext,
    ) -> Toolkit[TestenvRuntimeHookQAConfig]:
        """Return QA toolkit instance."""
        del context
        return TestenvRuntimeHookQAToolkit(config)

    async def test_connection(
        self,
        config: TestenvRuntimeHookQAConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """testenv provider does not use external connection."""
        del config, credentials_json, proxy_url
        return TestConnectionResult(
            success=True,
            message="Runtime hook QA provider is available.",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
