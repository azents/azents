"""Context window utility tests."""

from azents.engine.context.window import (
    compute_auto_compaction_protected_tokens,
    compute_effective_context_window_tokens,
    get_max_input_tokens,
)


class TestComputeEffectiveContextWindowTokens:
    """compute_effective_context_window_tokens tests."""

    def test_uses_main_model_when_compaction_model_missing(self) -> None:
        """Calculate from main model when compaction model limit is absent."""
        result = compute_effective_context_window_tokens(
            main_max_input_tokens=200_000,
            compaction_max_input_tokens=None,
        )

        assert result.effective_max_input_tokens == 200_000
        assert result.auto_compaction_threshold_tokens == 180_000

    def test_uses_smaller_compaction_model_context_window(self) -> None:
        """Use smaller compaction model limit as effective basis."""
        result = compute_effective_context_window_tokens(
            main_max_input_tokens=1_000_000,
            compaction_max_input_tokens=272_000,
        )

        assert result.effective_max_input_tokens == 272_000
        assert result.auto_compaction_threshold_tokens == 244_800


class TestComputeAutoCompactionProtectedTokens:
    """compute_auto_compaction_protected_tokens tests."""

    def test_uses_ten_percent_for_small_window(self) -> None:
        """Preserve 10 percent of small effective windows."""
        assert compute_auto_compaction_protected_tokens(32_000) == 3_200

    def test_caps_large_window_tail(self) -> None:
        """Do not let protected tail grow with large effective windows."""
        assert compute_auto_compaction_protected_tokens(272_000) == 12_000


class TestGetMaxInputTokens:
    """get_max_input_tokens tests."""

    def test_uses_capability_value_first(self) -> None:
        """Capability value takes precedence over LiteLLM lookup when present."""
        assert get_max_input_tokens(64_000, "unknown/provider-model") == 64_000

    def test_falls_back_when_capability_missing(self) -> None:
        """Return fallback value when capability value is absent."""
        assert get_max_input_tokens(None, "unknown/provider-model") == 128_000
