"""Stable Google Workspace service identities shared by management and execution."""

import enum


class GoogleService(enum.StrEnum):
    """Supported Google Workspace services."""

    CALENDAR = "calendar"
    DRIVE = "drive"
    GMAIL = "gmail"
