"""Keep transient GitHub credential inputs out of public validation failures."""

from azents.api.public.toolkit.v1.toolkit_validation import ToolkitSensitiveInputRoute


class GitHubUserRoute(ToolkitSensitiveInputRoute):
    """Preserve the GitHub user authorization validation error contract."""

    validation_message = "Invalid GitHub user authorization request."
