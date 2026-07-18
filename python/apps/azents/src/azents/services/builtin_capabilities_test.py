"""Trusted provider-hosted tool capability policy tests."""

from azents.core.enums import LLMProvider
from azents.services.builtin_capabilities import supported_builtin_capabilities


def test_openai_supported_family_gets_image_generation() -> None:
    """Project curated OpenAI mainline model support."""
    assert supported_builtin_capabilities(
        provider=LLMProvider.OPENAI,
        model_identifier="gpt-5.6-luna",
        metadata={"supports_web_search": True},
    ) == ["web_search", "image_generation"]


def test_explicit_false_overrides_curated_family() -> None:
    """Honor an explicit provider denial over the curated fallback."""
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.OPENAI,
            model_identifier="gpt-5.6-luna",
            metadata={"supports_image_generation": False},
        )
        == []
    )


def test_explicit_flag_enables_litellm_routed_provider() -> None:
    """Accept a trusted explicit flag for a non-OpenAI LiteLLM route."""
    assert supported_builtin_capabilities(
        provider=LLMProvider.ANTHROPIC,
        model_identifier="future-image-model",
        metadata={"supports_image_generation": True},
    ) == ["image_generation"]


def test_xai_function_calling_chat_model_gets_image_generation() -> None:
    """Project Imagine as an effective capability for xAI chat models."""
    metadata = {"mode": "chat", "supports_function_calling": True}

    assert supported_builtin_capabilities(
        provider=LLMProvider.XAI,
        model_identifier="grok-new-alias",
        metadata=metadata,
    ) == ["image_generation"]
    assert supported_builtin_capabilities(
        provider=LLMProvider.XAI_OAUTH,
        model_identifier="grok-new-alias",
        metadata=metadata,
    ) == ["image_generation"]


def test_xai_requires_chat_function_calling() -> None:
    """Do not expose the client tool when the language model cannot call it."""
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.XAI,
            model_identifier="grok-no-tools",
            metadata={"mode": "chat", "supports_function_calling": False},
        )
        == []
    )
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.XAI,
            model_identifier="grok-embedding",
            metadata={"mode": "embedding", "supports_function_calling": True},
        )
        == []
    )


def test_generic_image_output_modality_is_not_capability_evidence() -> None:
    """Do not infer the hosted tool from generic image output modality."""
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.GOOGLE_GEMINI,
            model_identifier="gemini-image",
            metadata={"supported_output_modalities": ["text", "image"]},
        )
        == []
    )


def test_chatgpt_experimental_tool_metadata_is_supported() -> None:
    """Use account-visible ChatGPT tool metadata when available."""
    assert supported_builtin_capabilities(
        provider=LLMProvider.CHATGPT_OAUTH,
        model_identifier="other-model",
        metadata={"experimental_supported_tools": ["image_generation"]},
    ) == ["web_search", "image_generation"]
