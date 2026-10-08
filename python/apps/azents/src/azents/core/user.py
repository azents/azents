"""Pure User update and account-deletion contracts."""

import dataclasses
import enum

from typing_extensions import TypedDict

from azents.core.locale import SupportedLocale


class UserUpdate(TypedDict, total=False):
    """User update schema (partial update)."""

    locale: SupportedLocale


@dataclasses.dataclass(frozen=True)
class NotFound:
    """User not found."""

    user_id: str


class UserDeletionStatus(enum.StrEnum):
    """Whether an account deletion found a retained User."""

    MISSING = "missing"
    ACCEPTED = "accepted"
