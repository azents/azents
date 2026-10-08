"""Canonical shared external channel management errors contracts."""


class ExternalChannelManagementNotFound(LookupError):
    """A management resource is unavailable to the caller."""


class ExternalChannelManagementGenerationChanged(RuntimeError):
    """A destructive request observed a newer Multi App generation."""
