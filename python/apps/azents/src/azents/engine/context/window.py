"""Context window management utilities."""

import dataclasses
import logging

import litellm

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD_RATIO = 0.9
"""Compaction trigger threshold ratio."""

PROTECTION_RATIO = 0.1
"""Auto compaction protected segment ratio."""

PROTECTION_MAX_TOKENS = 12_000
"""Maximum raw tail tokens preserved by auto compaction."""


@dataclasses.dataclass(frozen=True)
class EffectiveContextWindow:
    """Effective context window calculation result shared by runtime and API display."""

    main_max_input_tokens: int
    compaction_max_input_tokens: int | None
    effective_max_input_tokens: int
    auto_compaction_threshold_tokens: int


def compute_auto_compaction_threshold_tokens(max_input_tokens: int) -> int:
    """Calculate auto compaction trigger threshold token count.

    :param max_input_tokens: Effective context window token count
    :return: Token threshold that starts auto compaction
    """
    return int(max_input_tokens * COMPACTION_THRESHOLD_RATIO)


def compute_auto_compaction_protected_tokens(max_input_tokens: int) -> int:
    """Calculate raw tail token budget preserved by auto compaction.

    :param max_input_tokens: Effective context window token count
    :return: Token budget for raw tail events preserved after auto compaction
    """
    return min(int(max_input_tokens * PROTECTION_RATIO), PROTECTION_MAX_TOKENS)


def compute_effective_context_window_tokens(
    *,
    main_max_input_tokens: int,
    compaction_max_input_tokens: int | None,
) -> EffectiveContextWindow:
    """Calculate effective context window considering both main and compaction models.

    Runtime auto compaction uses the smaller of main model input limit and compaction
    model input limit. API/UI also display the same basis through this function.
    """
    effective_max_input_tokens = main_max_input_tokens
    if compaction_max_input_tokens is not None:
        effective_max_input_tokens = min(
            main_max_input_tokens,
            compaction_max_input_tokens,
        )
    return EffectiveContextWindow(
        main_max_input_tokens=main_max_input_tokens,
        compaction_max_input_tokens=compaction_max_input_tokens,
        effective_max_input_tokens=effective_max_input_tokens,
        auto_compaction_threshold_tokens=compute_auto_compaction_threshold_tokens(
            effective_max_input_tokens,
        ),
    )


def get_max_input_tokens(
    capability_max_input_tokens: int | None,
    litellm_model: str,
) -> int:
    """Resolve max_input_tokens with three-step fallback.

    1. Normalized capability contract
    2. LiteLLM model info
    3. 128,000 fallback

    :param capability_max_input_tokens: max_input_tokens from capability contract
    :param litellm_model: LiteLLM model string
    :return: max_input_tokens
    """
    if capability_max_input_tokens is not None:
        return capability_max_input_tokens

    try:
        info = litellm.get_model_info(litellm_model)
        max_input = info.get("max_input_tokens")
        if isinstance(max_input, int):
            return max_input
    except Exception:  # noqa: BLE001 — LiteLLM model catalog error shape differs by provider.
        logger.debug(
            "Failed to get model info from litellm",
            extra={"model": litellm_model},
            exc_info=True,
        )

    return 128_000
