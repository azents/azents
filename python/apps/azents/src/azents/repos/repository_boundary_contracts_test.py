"""Named repository snapshots and persisted JSON boundary contracts."""

import copy

import pytest

from azents.repos.runtime_profile.repository import RuntimeRecreationTargetSnapshot
from azents.repos.runtime_provider_bootstrap_operations import (
    PlatformDefaultCreationSeed,
)
from azents.repos.runtime_web.repository import RuntimeWebDeleteReceipt


def test_recreation_target_snapshot_names_each_fence_and_retains_unpacking() -> None:
    """Distinct fence values remain named and preserve the existing consumer."""
    snapshot = RuntimeRecreationTargetSnapshot(
        runtime_id="runtime-1",
        configuration_sequence=7,
        configuration_digest="digest-1",
        desired_generation=11,
    )
    assert snapshot.runtime_id == "runtime-1"
    assert snapshot.configuration_sequence == 7
    assert snapshot.configuration_digest == "digest-1"
    assert snapshot.desired_generation == 11
    runtime_id, sequence, digest, generation = snapshot
    assert (runtime_id, sequence, digest, generation) == (
        "runtime-1",
        7,
        "digest-1",
        11,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        (False, False),
        (True, True),
        (0, False),
        (1, True),
        ("", False),
        ("false", True),
        ([], False),
        ([1], True),
        ({}, False),
        ({"future": "value"}, True),
    ],
)
def test_known_persisted_flags_keep_historical_truthiness(
    value: object,
    expected: bool,
) -> None:
    """Compatibility decoding is independent from a stricter product policy."""
    seed_payload = {
        "set_as_platform_default_when_unset": value,
        "extension": {"future": [None, "opaque"]},
    }
    receipt_payload = {
        "deleted": value,
        "service_id": "service-1",
        "extension": {"future": [None, "opaque"]},
    }
    original_seed = copy.deepcopy(seed_payload)
    original_receipt = copy.deepcopy(receipt_payload)

    seed = PlatformDefaultCreationSeed.decode(seed_payload)
    receipt = RuntimeWebDeleteReceipt.decode(receipt_payload)

    assert seed.set_as_platform_default_when_unset is expected
    assert receipt.deleted is expected
    assert seed_payload == original_seed
    assert receipt_payload == original_receipt
    seed_payload["set_as_platform_default_when_unset"] = not expected
    receipt_payload["deleted"] = not expected
    assert seed.set_as_platform_default_when_unset is expected
    assert receipt.deleted is expected


def test_omitted_flags_and_absent_seed_decode_without_consuming_extensions() -> None:
    """Missing known fields stay false and opaque persistence is untouched."""
    opaque = {"extension": {"future": ["retained"]}}
    original = copy.deepcopy(opaque)
    assert not PlatformDefaultCreationSeed.decode(
        opaque
    ).set_as_platform_default_when_unset
    assert not PlatformDefaultCreationSeed.decode(
        None
    ).set_as_platform_default_when_unset
    assert not PlatformDefaultCreationSeed.decode({}).set_as_platform_default_when_unset
    assert not RuntimeWebDeleteReceipt.decode(opaque).deleted
    assert not RuntimeWebDeleteReceipt.decode({}).deleted
    assert opaque == original
