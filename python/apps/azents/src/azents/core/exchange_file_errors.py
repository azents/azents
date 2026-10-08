"""ExchangeFile domain failures and canonical location parsing."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class SessionNotFound:
    """Session not found."""


@dataclasses.dataclass(frozen=True)
class FileNotFound:
    """Exchange file not found."""


@dataclasses.dataclass(frozen=True)
class FileAccessDenied:
    """No Exchange file access permission."""


@dataclasses.dataclass(frozen=True)
class FileExpired:
    """Exchange file expired."""


@dataclasses.dataclass(frozen=True)
class FileUnavailable:
    """Cannot access original file in object storage."""


@dataclasses.dataclass(frozen=True)
class FileRetentionOwnerConflict:
    """Exchange file is already bound to another root session."""


ExchangeFileInputClaimError = (
    FileNotFound
    | FileAccessDenied
    | FileExpired
    | FileUnavailable
    | FileRetentionOwnerConflict
)


def exchange_object_key_from_uri(uri: str) -> str | None:
    """Return object key from Exchange file-location URI."""
    prefix = "exchange://"
    if not uri.startswith(prefix):
        return None
    object_key = uri.removeprefix(prefix)
    if not object_key:
        return None
    return object_key
