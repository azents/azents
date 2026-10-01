"""Assembly hints preserve only the physical candidate's saved authority."""

import dataclasses

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.model_assembly import ModelAssemblyMetadata


def test_capture_uses_typed_saved_family_not_mutable_diagnostics() -> None:
    """A later selection/catalog mutation cannot rewrite captured wire authority."""
    selection = AgentModelSelection(
        llm_provider_integration_id="integration",
        provider=LLMProvider.AWS_BEDROCK,
        model_identifier=(
            "arn:aws:bedrock:us-east-1:123456789012:"
            "application-inference-profile/opaque-profile"
        ),
        model_display_name="Saved model",
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family="claude",
        normalized_capabilities=ModelCapabilities(),
        model_snapshot={"family": "diagnostic-only-other-family"},
    )
    before = selection.normalized_capabilities.tool_calling.supported
    metadata = ModelAssemblyMetadata.from_selection(selection)
    assert metadata.model_developer is LLMModelDeveloper.ANTHROPIC
    assert metadata.model_family == "claude"
    assert metadata.capabilities == selection.normalized_capabilities
    assert metadata.capabilities is not selection.normalized_capabilities
    assert {field.name for field in dataclasses.fields(metadata)} == {
        "model_developer",
        "model_family",
        "capabilities",
    }
    selection.model_family = "changed-after-capture"
    selection.normalized_capabilities.tool_calling.supported = not before
    assert metadata.model_family == "claude"
    assert metadata.capabilities.tool_calling.supported is before
