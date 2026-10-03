"""Typed FIFO preparation and durable execution-owner conflicts."""


class MailboxPreparationStaleError(RuntimeError):
    """The FIFO head changed after its preparation snapshot was read."""


class MailboxOwnerGenerationStaleError(RuntimeError):
    """The Session owner generation changed before FIFO promotion."""
