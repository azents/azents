"""The explicit native component contract inventory, including relocated plays."""

from scripts.ci.observability import JUnitSummary

STORIES = {
    "src/features/agents/components/AgentRuntimeSettings.stories.tsx": (
        "Runtime Free",
        "Managed",
        "Browser Opt In",
        "Browser Enabled",
        "Browser Updating",
        "Removal Confirmation",
        "Removal Acknowledged",
        "Restart Confirmation",
        "Reset Confirmation",
        "Removing",
        "Loading",
        "Environment Variables Preview",
    ),
    "src/shared/toolkits/components/GitHubWizard.stories.tsx": (
        "Identity",
        "Personal Methods",
        "App Methods",
        "Platform Absent",
        "Per Identity Readiness",
        "Platform Incomplete",
        "Availability Loading",
        "Availability Error",
        "Metadata Loading",
        "Metadata Error",
        "Pat Input",
        "Self Managed User Input",
        "Self Managed App Input",
        "Platform Installations",
        "Verifying Close Allowed",
        "Connection Error",
        "Candidate Inline",
        "Candidate Metadata Error",
        "Candidate Close Without Publication",
        "Features",
        "Runtime Off",
        "Runtime Risk Unacknowledged",
        "Final Review",
        "Agent Review",
        "Personal Review",
        "Publication Pending",
        "Publication Failed",
        "Uncertain Publication",
        "Saved",
        "Target Denied",
        "Transport Changed",
        "Mobile Review",
        "Selection Geometry Mobile",
        "Installed App Light Contrast",
        "Installed App Dark Contrast",
    ),
    "src/features/chat/components/ChatSessionView.stories.tsx": (
        "Conversation",
        "Browser Disabled",
        "Browser Enabled",
        "Mobile Panel",
        "Mobile Chat",
        "Runtime Panel",
        "Terminal Panel",
        "Loading History",
        "Subagent Conversation",
        "Policy Denied Terminal",
        "Runtime Free Terminal",
    ),
}


def portfolio_complete(summary: JUnitSummary) -> bool:
    """Require every selected state/play identity exactly once."""
    expected = {f"{path}::{name}" for path, names in STORIES.items() for name in names}
    return (
        summary.tests == len(expected)
        and {case.node_id for case in summary.cases} == expected
    )
