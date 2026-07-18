"""Trusted policy for effective built-in model capabilities."""

from collections.abc import Mapping, Sequence

from azents.core.enums import LLMProvider

_IMAGE_GENERATION_OPENAI_MODEL_PREFIXES = (
    "gpt-5",
    "gpt-4.1",
    "gpt-4o",
    "o3",
)


def supported_builtin_capabilities(
    *,
    provider: LLMProvider,
    model_identifier: str,
    metadata: Mapping[str, object],
) -> list[str]:
    """Return built-in tools supported by trusted provider metadata and policy."""
    supported: list[str] = []
    if (
        metadata.get("supports_web_search") is True
        or provider == LLMProvider.CHATGPT_OAUTH
    ):
        supported.append("web_search")
    if _supports_image_generation(
        provider=provider,
        model_identifier=model_identifier,
        metadata=metadata,
    ):
        supported.append("image_generation")
    return supported


def _supports_image_generation(
    *,
    provider: LLMProvider,
    model_identifier: str,
    metadata: Mapping[str, object],
) -> bool:
    explicit = metadata.get("supports_image_generation")
    if isinstance(explicit, bool):
        return explicit

    for key in ("supported_builtin_tools", "experimental_supported_tools"):
        value = metadata.get(key)
        if _string_sequence_contains(value, "image_generation"):
            return True

    if provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}:
        return (
            metadata.get("mode") == "chat"
            and metadata.get("supports_function_calling") is True
        )
    if provider not in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return False
    normalized = model_identifier.removeprefix("openai/").lower()
    return normalized.startswith(_IMAGE_GENERATION_OPENAI_MODEL_PREFIXES)


def _string_sequence_contains(value: object, expected: str) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    return any(item == expected for item in value)
