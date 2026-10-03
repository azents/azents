"""Historical Memory settings scope shared by query and product contracts."""

import enum


class HistoricalMemorySettingsScope(enum.StrEnum):
    """One exact Historical Memory settings source scope."""

    TEAM = "team"
    USER = "user"
