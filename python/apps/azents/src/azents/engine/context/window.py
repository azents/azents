"""Context window management utilities."""

import dataclasses
import logging

import litellm

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD_RATIO = 0.9
"""Compaction trigger threshold ratio."""


@dataclasses.dataclass(frozen=True)
class EffectiveContextWindow:
    """Effective context window calculation result shared by runtime and API display."""

    main_max_input_tokens: int
    compaction_max_input_tokens: int | None
    context_window_tokens: int | None
    effective_max_input_tokens: int
    auto_compaction_threshold_tokens: int


@dataclasses.dataclass(frozen=True)
class ResolvedModelInputTokens:
    """Resolved model input limits after metadata fallback and user intent."""

    default_input_tokens: int
    max_input_tokens: int
    effective_input_tokens: int


def compute_auto_compaction_threshold_tokens(max_input_tokens: int) -> int:
    """Calculate auto compaction trigger threshold token count.

    :param max_input_tokens: Effective context window token count
    :return: Token threshold that starts auto compaction
    """
    return int(max_input_tokens * COMPACTION_THRESHOLD_RATIO)


def compute_effective_context_window_tokens(
    *,
    main_max_input_tokens: int,
    compaction_max_input_tokens: int | None,
    context_window_tokens: int | None = None,
) -> EffectiveContextWindow:
    """Calculate effective context window considering model and Agent caps.

    Runtime auto compaction uses the smallest value among the main model input
    limit, compaction model input limit, and optional Agent context window cap.
    API/UI also display the same basis through this function.
    """
    candidates = [main_max_input_tokens]
    if compaction_max_input_tokens is not None:
        candidates.append(compaction_max_input_tokens)
    if context_window_tokens is not None:
        candidates.append(context_window_tokens)
    effective_max_input_tokens = min(candidates)
    return EffectiveContextWindow(
        main_max_input_tokens=main_max_input_tokens,
        compaction_max_input_tokens=compaction_max_input_tokens,
        context_window_tokens=context_window_tokens,
        effective_max_input_tokens=effective_max_input_tokens,
        auto_compaction_threshold_tokens=compute_auto_compaction_threshold_tokens(
            effective_max_input_tokens,
        ),
    )


def resolve_model_input_tokens(
    capability_default_input_tokens: int | None,
    capability_max_input_tokens: int | None,
    litellm_model: str,
    context_window_tokens: int | None,
) -> ResolvedModelInputTokens:
    """Resolve default, maximum, and effective model input limits.

    The normalized capability is authoritative. LiteLLM and the 128,000-token
    fallback fill missing maximum metadata. A missing default uses the resolved
    maximum, while explicit user intent is clamped to that maximum.

    :param capability_default_input_tokens: provider default input window
    :param capability_max_input_tokens: max_input_tokens from capability contract
    :param litellm_model: LiteLLM model string
    :param context_window_tokens: nullable user-configured input cap
    :return: resolved input-token limits
    """
    litellm_max_input_tokens: int | None = None
    if capability_max_input_tokens is None:
        try:
            info = litellm.get_model_info(litellm_model)
            max_input = info.get("max_input_tokens")
            if isinstance(max_input, int) and not isinstance(max_input, bool):
                if max_input > 0:
                    litellm_max_input_tokens = max_input
        except Exception:  # noqa: BLE001 — LiteLLM catalog errors vary by provider.
            logger.debug(
                "Failed to get model info from litellm",
                extra={"model": litellm_model},
                exc_info=True,
            )

    if capability_max_input_tokens is not None:
        max_input_tokens = capability_max_input_tokens
    elif capability_default_input_tokens is not None:
        max_input_tokens = max(
            capability_default_input_tokens,
            litellm_max_input_tokens or capability_default_input_tokens,
        )
    else:
        max_input_tokens = litellm_max_input_tokens or 128_000

    default_input_tokens = min(
        capability_default_input_tokens or max_input_tokens,
        max_input_tokens,
    )
    effective_input_tokens = (
        default_input_tokens
        if context_window_tokens is None
        else min(context_window_tokens, max_input_tokens)
    )
    return ResolvedModelInputTokens(
        default_input_tokens=default_input_tokens,
        max_input_tokens=max_input_tokens,
        effective_input_tokens=effective_input_tokens,
    )
