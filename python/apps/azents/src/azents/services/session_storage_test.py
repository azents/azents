"""Session data file storage utility tests.

Validate guess_media_type and validate_filename functions.
"""

import pytest

from azents.services.session_storage import (
    guess_media_type,
    validate_filename,
)

# ---------------------------------------------------------------------------
# guess_media_type
# ---------------------------------------------------------------------------


class TestGuessMediaType:
    """MIME type guessing tests."""

    def test_txt_file(self) -> None:
        """Guess MIME type of text file."""
        assert guess_media_type("note.txt") == "text/plain"

    def test_json_file(self) -> None:
        """Guess MIME type of JSON file."""
        assert guess_media_type("config.json") == "application/json"

    def test_png_file(self) -> None:
        """Guess MIME type of PNG image."""
        assert guess_media_type("image.png") == "image/png"

    def test_unknown_extension(self) -> None:
        """Unknown extension returns application/octet-stream."""
        assert guess_media_type("data.xyz123") == "application/octet-stream"

    def test_no_extension(self) -> None:
        """Missing extension returns application/octet-stream."""
        assert guess_media_type("Makefile") == "application/octet-stream"


# ---------------------------------------------------------------------------
# validate_filename
# ---------------------------------------------------------------------------


class TestValidateFilename:
    """Filename validation tests."""

    def test_simple_filename(self) -> None:
        """Simple filename passes."""
        validate_filename("note.txt")

    def test_nested_path(self) -> None:
        """Nested path also passes."""
        validate_filename("skills/my-skill/SKILL.md")

    def test_empty_raises(self) -> None:
        """Empty filename raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_filename("")

    def test_absolute_path_raises(self) -> None:
        """Absolute path raises ValueError."""
        with pytest.raises(ValueError, match="Absolute paths not allowed"):
            validate_filename("/etc/passwd")

    def test_dot_dot_traversal_raises(self) -> None:
        """Path traversal raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filename"):
            validate_filename("../secret.txt")

    def test_nested_dot_dot_raises(self) -> None:
        """Nested path traversal also raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filename"):
            validate_filename("skills/../../etc/passwd")
