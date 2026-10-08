"""Saved Memory scope shared by persistence and product contracts."""

import enum


class MemoryScope(enum.StrEnum):
    """Memory scope."""

    AGENT = "agent"
    USER = "user"
