"""Shared External Channel automatic-title constants and normalization."""

DISCORD_INITIAL_THREAD_TITLE_LABEL = "discord_initial_thread_title"
DISCORD_THREAD_TITLE_MAX_CHARS = 100


def normalize_discord_thread_title(value: str | None) -> str | None:
    """Return one non-empty provider-valid Discord thread title."""
    normalized = "" if value is None else " ".join(value.split())
    if not normalized:
        return None
    return normalized[:DISCORD_THREAD_TITLE_MAX_CHARS]
