"""AgentSession handle generation."""

import secrets
from collections.abc import Sequence

from azents.core.bip39_english_words import BIP39_ENGLISH_WORDS

SESSION_HANDLE_WORD_COUNT = 3


def generate_session_handle(words: Sequence[str] = BIP39_ENGLISH_WORDS) -> str:
    """Generate a stable human-readable session handle candidate."""
    if len(words) == 0:
        raise ValueError("Session handle word source must not be empty")
    return "-".join(secrets.choice(words) for _ in range(SESSION_HANDLE_WORD_COUNT))
