"""LLM catalog projection ordering tests."""

from azents.services.llm_catalog import model_freshness_rank


def test_freshness_rank_prefers_newer_model_generation() -> None:
    """Calculate a rank that sorts newer generation model identifiers first."""
    models = ["gpt-3.5-turbo", "gpt-5.5-mini", "gpt-4o", "gpt-5"]

    assert sorted(models, key=model_freshness_rank, reverse=True) == [
        "gpt-5.5-mini",
        "gpt-5",
        "gpt-4o",
        "gpt-3.5-turbo",
    ]
