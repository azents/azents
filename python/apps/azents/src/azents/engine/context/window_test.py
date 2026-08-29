"""Context window utility tests."""

import pytest

from azents.engine.context.window import (
    compute_effective_context_window_tokens,
    resolve_model_input_tokens,
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

    def test_uses_smaller_agent_context_window_cap(self) -> None:
        """Use Agent context window cap when it is the smallest value."""
        result = compute_effective_context_window_tokens(
            main_max_input_tokens=1_000_000,
            compaction_max_input_tokens=272_000,
            context_window_tokens=128_000,
        )

        assert result.effective_max_input_tokens == 128_000
        assert result.auto_compaction_threshold_tokens == 115_200

    def test_allows_context_window_cap_larger_than_model_limit(self) -> None:
        """Larger Agent cap is stored as intent but model limits still win."""
        result = compute_effective_context_window_tokens(
            main_max_input_tokens=128_000,
            compaction_max_input_tokens=128_000,
            context_window_tokens=200_000,
        )

        assert result.effective_max_input_tokens == 128_000
        assert result.auto_compaction_threshold_tokens == 115_200


class TestResolveModelInputTokens:
    """resolve_model_input_tokens tests."""

    def test_uses_maximum_as_default_when_default_missing(self) -> None:
        """Maximum-only capabilities preserve the legacy default behavior."""
        result = resolve_model_input_tokens(
            None,
            64_000,
            "unknown/provider-model",
            None,
        )

        assert result.default_input_tokens == 64_000
        assert result.max_input_tokens == 64_000
        assert result.effective_input_tokens == 64_000

    def test_uses_distinct_default_without_user_cap(self) -> None:
        """An unset user cap uses the provider default."""
        result = resolve_model_input_tokens(
            272_000,
            872_000,
            "unknown/provider-model",
            None,
        )

        assert result.default_input_tokens == 272_000
        assert result.max_input_tokens == 872_000
        assert result.effective_input_tokens == 272_000

    def test_uses_user_cap_between_default_and_maximum(self) -> None:
        """Explicit long-context intent may exceed the provider default."""
        result = resolve_model_input_tokens(
            272_000,
            872_000,
            "unknown/provider-model",
            500_000,
        )

        assert result.effective_input_tokens == 500_000

    def test_clamps_user_cap_to_maximum(self) -> None:
        """Explicit user intent cannot exceed the provider maximum."""
        result = resolve_model_input_tokens(
            272_000,
            872_000,
            "unknown/provider-model",
            1_000_000,
        )

        assert result.effective_input_tokens == 872_000

    def test_clamps_inconsistent_default_to_maximum(self) -> None:
        """Provider metadata cannot make the ordinary window exceed its maximum."""
        result = resolve_model_input_tokens(
            200_000,
            128_000,
            "unknown/provider-model",
            None,
        )

        assert result.default_input_tokens == 128_000
        assert result.effective_input_tokens == 128_000

    def test_preserves_known_default_when_litellm_maximum_is_smaller(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fallback metadata cannot reduce a provider-authoritative default."""
        monkeypatch.setattr(
            "azents.engine.context.window.litellm.get_model_info",
            lambda _: {"max_input_tokens": 128_000},
        )

        result = resolve_model_input_tokens(
            272_000,
            None,
            "provider/model",
            None,
        )

        assert result.default_input_tokens == 272_000
        assert result.max_input_tokens == 272_000

    def test_falls_back_when_capability_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Return the stable fallback when capability and LiteLLM values are absent."""
        monkeypatch.setattr(
            "azents.engine.context.window.litellm.get_model_info",
            lambda _: {},
        )

        result = resolve_model_input_tokens(
            None,
            None,
            "unknown/provider-model",
            None,
        )

        assert result.default_input_tokens == 128_000
        assert result.max_input_tokens == 128_000
        assert result.effective_input_tokens == 128_000
