"""Session data file storage utilities.

Provides common utilities such as MIME type guessing and filename validation.
"""

import mimetypes
from pathlib import PurePosixPath

_DEFAULT_MEDIA_TYPE = "application/octet-stream"


def guess_media_type(filename: str) -> str:
    """Guess MIME type from filename.

    :param filename: Filename
    :return: MIME type (application/octet-stream when cannot guess)
    """
    mime, _ = mimetypes.guess_type(filename)
    return mime or _DEFAULT_MEDIA_TYPE


def validate_filename(filename: str) -> None:
    """Prevent path traversal attacks in filename.

    :param filename: Filename to validate
    :raises ValueError: When empty string, path traversal, or absolute path is included
    """
    if not filename:
        raise ValueError("Filename must not be empty")
    if filename.startswith("/"):
        raise ValueError(f"Absolute paths not allowed: {filename}")
    parts = PurePosixPath(filename).parts
    if any(p == ".." for p in parts):
        raise ValueError(f"Invalid filename: {filename}")
