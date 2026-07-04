"""Session handle generation tests."""

from azents.core.bip39_english_words import BIP39_ENGLISH_WORDS
from azents.core.session_handle import generate_session_handle


def test_bip39_wordlist_snapshot_shape() -> None:
    """Vendored BIP-39 English wordlist has expected stable shape."""
    assert len(BIP39_ENGLISH_WORDS) == 2048
    assert BIP39_ENGLISH_WORDS[0] == "abandon"
    assert BIP39_ENGLISH_WORDS[-1] == "zoo"


def test_generate_session_handle_uses_three_words() -> None:
    """Generated session handles use three hyphen-separated wordlist entries."""
    handle = generate_session_handle(words=("alpha", "bravo", "charlie"))

    parts = handle.split("-")
    assert len(parts) == 3
    assert set(parts) <= {"alpha", "bravo", "charlie"}
