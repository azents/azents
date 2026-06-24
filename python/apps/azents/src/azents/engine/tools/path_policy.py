"""Runtime file tool path guidance."""

RUNTIME_ACCESSIBLE_PATHS_MSG = (
    "Use absolute runtime paths. /workspace/agent is the durable working directory, "
    "and /tmp is temporary scratch space. Use import_file for exchange:// uploads "
    "and present_file to share files back to the user."
)
