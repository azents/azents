"""Deterministic provider-tool live proxy synchronization tests."""

import threading

from support import image_generation_openai_proxy as proxy


def test_provider_tool_live_barrier_waits_for_explicit_release() -> None:
    """Keep the provider stream blocked until the test explicitly releases it."""
    barrier = proxy._ProviderToolLiveBarrier()
    barrier.arm()
    result: list[bool] = []

    waiter = threading.Thread(target=lambda: result.append(barrier.wait_for_release()))
    waiter.start()

    assert barrier.wait_until_reached(timeout=1)
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": False,
    }

    barrier.release()
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert result == [True]
    assert barrier.evidence() == {
        "armed": True,
        "reached": True,
        "released": True,
    }


def test_provider_tool_live_barrier_rejects_unarmed_wait() -> None:
    """Fail immediately when a provider response reaches an unarmed barrier."""
    barrier = proxy._ProviderToolLiveBarrier()

    assert not barrier.wait_for_release()
