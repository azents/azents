"""Chat session context inspector tests."""

import datetime

from azents.api.public.chat.v1.data import SessionContextSystemPromptResponse
from azents.core.enums import EventKind
from azents.engine.events.types import (
    Event,
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
)

from .context import (
    SessionContextSystemPrompt,
    _build_breakdown,  # pyright: ignore[reportPrivateUsage]
)

_NOW = datetime.datetime.now(datetime.UTC)


def _fragment(
    id: str,
    *,
    source: str,
    content: str,
) -> SystemPromptFragmentPayload:
    """Create a prompt analysis fragment."""
    return SystemPromptFragmentPayload.model_validate(
        {
            "id": id,
            "source": source,
            "label": id,
            "content": content,
            "preview": content,
            "length": len(content),
        }
    )


def _analysis(*, final: bool) -> SystemPromptAnalysisPayload:
    """Create system and developer prompt analysis."""
    return SystemPromptAnalysisPayload(
        agent_prompt=_fragment("agent", source="agent", content="agent"),
        toolkit_prompts=[_fragment("toolkit", source="toolkit", content="toolkit")],
        developer_prompts=[
            _fragment("role", source="developer_prompt", content="role"),
            _fragment("mode", source="developer_prompt", content="mode text"),
        ],
        final_prompt=(
            _fragment("final", source="final", content="final prompt")
            if final
            else None
        ),
    )


def _turn_event(analysis: SystemPromptAnalysisPayload) -> Event:
    """Create a turn marker carrying prompt analysis."""
    return Event(
        id="event".rjust(32, "0"),
        session_id="session-1",
        kind=EventKind.TURN_MARKER,
        payload=TurnMarkerPayload(
            run_id="run-1",
            usage=TokenUsagePayload(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                raw={},
            ),
            system_prompt=analysis,
        ),
        model_order=1000,
        created_at=_NOW,
    )


def test_developer_prompts_project_in_order_through_public_response() -> None:
    """Keep standalone developer inputs visible in service and API projections."""
    prompt = SessionContextSystemPrompt.from_payload(_analysis(final=True))

    assert [fragment.id for fragment in prompt.developer_prompts] == ["role", "mode"]
    assert [fragment.source for fragment in prompt.developer_prompts] == [
        "developer_prompt",
        "developer_prompt",
    ]

    response = SessionContextSystemPromptResponse.from_domain(prompt)
    assert [fragment.id for fragment in response.developer_prompts] == [
        "role",
        "mode",
    ]
    assert response.developer_prompts[0].source == "developer_prompt"


def test_breakdown_counts_developer_prompts_with_and_without_final_prompt() -> None:
    """Count standalone developer inputs outside the composed system prompt."""
    with_final = _build_breakdown([_turn_event(_analysis(final=True))])
    without_final = _build_breakdown([_turn_event(_analysis(final=False))])

    assert [(segment.key, segment.tokens) for segment in with_final] == [
        ("system", len("final prompt") + len("role") + len("mode text"))
    ]
    assert [(segment.key, segment.tokens) for segment in without_final] == [
        (
            "system",
            len("agent") + len("toolkit") + len("role") + len("mode text"),
        )
    ]
