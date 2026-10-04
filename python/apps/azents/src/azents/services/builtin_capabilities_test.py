"""Trusted effective built-in tool capability policy tests."""

from azents.core.builtin_tools import supported_builtin_capabilities
from azents.core.enums import LLMProvider


def test_openai_function_capable_conversation_gets_client_image_generation() -> None:
    """Use declared client prerequisites rather than model-family predictions."""
    assert supported_builtin_capabilities(
        provider=LLMProvider.OPENAI,
        model_identifier="opaque-conversation-model",
        metadata={
            "supports_web_search": True,
            "supports_function_calling": True,
            "mode": "responses",
        },
    ) == ["web_search", "image_generation"]


def test_hosted_image_denial_does_not_disable_openai_client_tool() -> None:
    """A tool-capable GPT-6 model may generate images through the client."""
    for provider in (LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH):
        assert "image_generation" in supported_builtin_capabilities(
            provider=provider,
            model_identifier="gpt-6-astra",
            metadata={
                "supports_image_generation": False,
                "supports_function_calling": True,
                "mode": "responses",
            },
        )


def test_openai_client_tool_requires_function_calling_chat_model() -> None:
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.OPENAI,
            model_identifier="gpt-6-astra",
            metadata={"supports_function_calling": False},
        )
        == []
    )
    assert (
        supported_builtin_capabilities(
            provider=LLMProvider.OPENAI,
            model_identifier="gpt-6-astra",
            metadata={"mode": "image_generation"},
        )
        == []
    )


def test_explicit_flag_enables_provider_routed_model() -> None:
    """Accept a trusted explicit flag for a non-OpenAI provider route."""
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
        metadata={
            "experimental_supported_tools": ["image_generation"],
            "supports_function_calling": True,
            "mode": "responses",
        },
    ) == ["web_search", "image_generation"]
