"""Safe domain failures for mutations racing Agent decommission admission."""


class AgentMutationReadOnly(Exception):
    """The authorized target is being deleted and cannot accept new user changes."""


class AgentMutationTargetMissing(Exception):
    """The authorized target disappeared before its mutation could commit."""
