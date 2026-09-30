"""Offline checks for deterministic inference-profile provider fixtures."""

import threading

import pytest

from support import image_generation_openai_proxy as proxy


@pytest.mark.parametrize(
    ("scenario", "tier"),
    [
        ("served-ultrafast", "ultrafast"),
        ("missing-tier", None),
        ("served-default", "default"),
        ("served-priority", "priority"),
        ("retry", "ultrafast"),
        ("prepared", "ultrafast"),
        ("queued", "default"),
    ],
)
def test_completed_profile_fixture_reports_actual_tier(
    scenario: str, tier: str | None
) -> None:
    """Actual tier comes from the fixture, independently of requested speed."""
    message = f"Ultrafast E2E {scenario} synthetic-request"
    request: dict[str, object] = {
        "model": "gpt-6-astra",
        "service_tier": "ultrafast",
        "input": [{"role": "user", "content": message}],
    }
    # Construct only payload data: no listener, socket, or HTTP handler startup.
    handler = object.__new__(proxy._Handler)
    response = handler._response(
        request=request,
        response_id="resp_offline_profile",
        model="gpt-6-astra",
        output=[],
    )
    assert proxy.inference_profile_scenario(message) == scenario
    if tier is None:
        assert "service_tier" not in response
    else:
        assert response["service_tier"] == tier
    assert response["status"] == "completed"
    usage = response["usage"]
    assert isinstance(usage, dict)
    assert usage["total_tokens"] == 2
    assert request["service_tier"] == "ultrafast"


@pytest.mark.parametrize(
    "message",
    [None, "Ordinary prompt", "Ultrafast E2E unregistered scenario", "Ultrafast E2E "],
)
def test_profile_fixture_does_not_capture_unrelated_requests(
    message: str | None,
) -> None:
    """Only explicit named scenarios may bypass the upstream provider mock."""
    assert proxy.inference_profile_scenario(message) is None


def test_profile_barrier_requires_explicit_release() -> None:
    """Observe preparation before releasing the response without scheduling sleeps."""
    barrier = proxy._ProviderToolLiveBarrier()
    barrier.arm()
    results: list[bool] = []
    thread = threading.Thread(target=lambda: results.append(barrier.wait_for_release()))
    thread.start()
    try:
        assert barrier.wait_until_reached(timeout=1)
        assert barrier.evidence() == {
            "armed": True,
            "reached": True,
            "released": False,
        }
    finally:
        barrier.release()
        thread.join(timeout=1)
    assert not thread.is_alive()
    assert results == [True]


def test_profile_title_fixture_is_separate_from_main_speed_scenario() -> None:
    """Classify auxiliary title calls without treating them as main inference."""
    request: dict[str, object] = {
        "instructions": "Create a brief title from the request",
        "input": [
            {
                "role": "user",
                "content": (
                    "Create a title from this request:\n"
                    "Ultrafast E2E served-ultrafast synthetic-request"
                ),
            }
        ],
    }
    assert proxy.is_inference_profile_title_request(request)
    assert proxy.inference_profile_scenario(proxy._last_user_text(request)) is None
    request["instructions"] = "Independent main inference"
    assert not proxy.is_inference_profile_title_request(request)
