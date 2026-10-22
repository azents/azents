"""Stable Google Workspace service identities shared by management and execution."""

import enum


class GoogleService(enum.StrEnum):
    """Supported Google Workspace services."""

    CALENDAR = "calendar"
    DRIVE = "drive"
    GMAIL = "gmail"


class GoogleToolGroup(enum.StrEnum):
    """Closed capability selections; Google scopes remain independent evidence."""

    GMAIL_READ = "gmail_read"
    GMAIL_LABELS = "gmail_labels"
    GMAIL_DRAFTS = "gmail_drafts"
    GMAIL_SEND = "gmail_send"
    GMAIL_ORGANIZE = "gmail_organize"
    GMAIL_FILTERS = "gmail_filters"
    CALENDAR_READ = "calendar_read"
    CALENDAR_AVAILABILITY = "calendar_availability"
    CALENDAR_EVENTS = "calendar_events"
    CALENDAR_STATUS = "calendar_status"
    CALENDAR_CREATE = "calendar_create"
    DRIVE_READ = "drive_read"
    DRIVE_FILES = "drive_files"
    DRIVE_SHARING = "drive_sharing"
    DRIVE_OWNERSHIP = "drive_ownership"
