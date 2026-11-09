"""Admission assertions use delivered control identity, not transient Run phase."""

from tests.required.public.external_channel_scenarios import (
    _ProviderState,
    _slack_admission_control_posts,
)


def test_admission_posts_ignore_concurrent_reply_and_presence_phase() -> None:
    state = _ProviderState.model_validate(
        {
            "request_counts": {"chat.postMessage": 5, "chat.delete": 1},
            "presence": [
                {"operation": "agents.sessions.setStatus", "desired_state": "idle"}
            ],
            "deliveries": [
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "approval_request_id": "approval",
                },
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "safe_category": "session_presence_joined",
                },
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "safe_category": "activity_tracker",
                },
                {"operation": "chat.postMessage", "outcome": "delivered"},
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "approval_request_id": "foreign",
                },
                {
                    "operation": "chat.update",
                    "outcome": "delivered",
                    "safe_category": "activity_tracker",
                },
            ],
        }
    )
    posts = _slack_admission_control_posts(state, "approval")
    assert len(posts) == 3
    assert posts[0].approval_request_id == "approval"
    assert [post.safe_category for post in posts[1:]] == [
        "session_presence_joined",
        "activity_tracker",
    ]
    state.deliveries.append(posts[-1])
    assert len(_slack_admission_control_posts(state, "approval")) == 4


def test_missing_or_failed_control_cannot_satisfy_admission_post_count() -> None:
    state = _ProviderState.model_validate(
        {
            "request_counts": {"chat.postMessage": 3},
            "deliveries": [
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "approval_request_id": "approval",
                },
                {
                    "operation": "chat.postMessage",
                    "outcome": "delivered",
                    "safe_category": "session_presence_joined",
                },
                {
                    "operation": "chat.postMessage",
                    "outcome": "failed",
                    "safe_category": "activity_tracker",
                },
            ],
        }
    )
    assert len(_slack_admission_control_posts(state, "approval")) == 2
