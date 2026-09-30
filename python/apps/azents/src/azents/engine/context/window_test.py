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
            None,
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
            None,
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
            None,
            500_000,
        )

        assert result.effective_input_tokens == 500_000

    def test_clamps_user_cap_to_maximum(self) -> None:
        """Explicit user intent cannot exceed the provider maximum."""
        result = resolve_model_input_tokens(
            272_000,
            872_000,
            None,
            1_000_000,
        )

        assert result.effective_input_tokens == 872_000

    def test_clamps_inconsistent_default_to_maximum(self) -> None:
        """Provider metadata cannot make the ordinary window exceed its maximum."""
        result = resolve_model_input_tokens(
            200_000,
            128_000,
            None,
            None,
        )

        assert result.default_input_tokens == 128_000
        assert result.effective_input_tokens == 128_000

    def test_preserves_known_default_when_source_maximum_is_smaller(self) -> None:
        """Fallback metadata cannot reduce a provider-authoritative default."""
        result = resolve_model_input_tokens(
            272_000,
            None,
            128_000,
            None,
        )

        assert result.default_input_tokens == 272_000
        assert result.max_input_tokens == 272_000

    def test_falls_back_when_capability_and_source_are_missing(self) -> None:
        """Return the stable fallback only when all metadata is absent."""
        result = resolve_model_input_tokens(
            None,
            None,
            None,
            None,
        )

        assert result.default_input_tokens == 128_000
        assert result.max_input_tokens == 128_000
        assert result.effective_input_tokens == 128_000

    def test_default_only_does_not_apply_smaller_fallback(self) -> None:
        """A provider default alone is its maximum instead of the 128k fallback."""
        result = resolve_model_input_tokens(272_000, None, None, None)
        assert result.default_input_tokens == 272_000
        assert result.max_input_tokens == 272_000
        assert result.effective_input_tokens == 272_000

    def test_source_maximum_fills_missing_maximum_without_changing_default(
        self,
    ) -> None:
        """Captured source data supplies the ceiling, not different saved intent."""
        result = resolve_model_input_tokens(128_000, None, 1_000_000, 700_000)
        assert result.default_input_tokens == 128_000
        assert result.max_input_tokens == 1_000_000
        assert result.effective_input_tokens == 700_000

    def test_normalized_maximum_wins_over_source(self) -> None:
        """The retained source cannot upgrade an authoritative saved maximum."""
        result = resolve_model_input_tokens(None, 128_000, 1_000_000, 900_000)
        assert result.default_input_tokens == 128_000
        assert result.max_input_tokens == 128_000
        assert result.effective_input_tokens == 128_000

    @pytest.mark.parametrize("source_maximum", [None, 0, -10, True, False])
    def test_invalid_or_absent_source_maximum_remains_unknown(
        self,
        source_maximum: int | None,
    ) -> None:
        """Nonpositive or boolean source values never become token limits."""
        result = resolve_model_input_tokens(None, None, source_maximum, None)
        assert result.effective_input_tokens == 128_000
