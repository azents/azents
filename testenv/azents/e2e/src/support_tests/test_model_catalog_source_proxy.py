"""Docker-free checks for the inert inference-profile model source fixture."""

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from support import image_generation_openai_proxy as proxy
from support.image_generation_openai_proxy import _inference_profile_source_payload

_MODELS = ("gpt-5.5", "gpt-5.5-mini", "gpt-6-astra", "gpt-5.6-sol")
_FULL_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
_RATES = {
    "input_cost_per_token": Decimal("0.000001"),
    "output_cost_per_token": Decimal("0.000002"),
    "cache_read_input_token_cost": Decimal("0.0000001"),
    "cache_creation_input_token_cost": Decimal("0.000001"),
}


def test_catalog_source_is_exact_openai_model_data_not_a_provider_program() -> None:
    """The serialized source uses bare OpenAI addresses and independent facts."""
    payload = _inference_profile_source_payload("baseline")
    serialized = json.dumps(payload, allow_nan=False)
    restored = json.loads(serialized)

    assert restored == payload
    assert tuple(restored) == _MODELS
    for identifier, model in restored.items():
        assert "/" not in identifier
        assert model["litellm_provider"] == "openai"
        assert model["display_name"] == identifier
        assert model["mode"] == "responses"
        assert model["supported_endpoints"] == ["/v1/responses"]
        assert model["max_input_tokens"] == 128_000
        assert model["supported_modalities"] == ["text", "image", "pdf"]
        assert model["supported_output_modalities"] == ["text"]
        assert model["supports_vision"] is True
        assert model["supports_pdf_input"] is True
        assert model["supports_function_calling"] is True
        assert model["supports_parallel_function_calling"] is True
        assert model["supports_response_schema"] is True
        assert {
            "id",
            "models",
            "api_pattern",
            "match",
            "prices",
            "input_modalities",
            "output_modalities",
        }.isdisjoint(model)
        assert "supports_strict_function_schema" not in model


def test_proxy_import_is_stdlib_only_without_starting_a_listener(
    tmp_path: Path,
) -> None:
    """Mirror the standalone image import with site packages and cwd isolated."""
    script_path = Path(proxy.__file__).resolve()
    smoke = """
import dataclasses
import json
import runpy
import sys

assert sys.flags.isolated == 1
assert sys.flags.no_site == 1
namespace = runpy.run_path(sys.argv[1], run_name="fixture_stdlib_import")
assert "pydantic" not in sys.modules
decode = namespace["_decode_inference_profile_source_control"]
source = namespace["_inference_profile_source_payload"]
for variant in ("baseline", "refreshed", "missing-model"):
    control = decode(json.dumps({"variant": variant}).encode())
    assert dataclasses.is_dataclass(control)
    assert control.variant == variant
    try:
        control.variant = "baseline"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Source control must be frozen.")
    assert len(source(control.variant)) == (3 if variant == "missing-model" else 4)
print("stdlib-only proxy import and source controls verified")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", smoke, str(script_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert result.stderr == ""
    assert result.stdout.strip() == (
        "stdlib-only proxy import and source controls verified"
    )


@pytest.mark.parametrize("identifier", _MODELS)
def test_catalog_rates_preserve_per_million_fixture_arithmetic(
    identifier: str,
) -> None:
    """Conversion to per-token numbers preserves all four original prices."""
    restored = json.loads(
        json.dumps(_inference_profile_source_payload("baseline"), allow_nan=False),
        parse_float=Decimal,
    )
    model = restored[identifier]
    for field, expected_rate in _RATES.items():
        assert model[field] == expected_rate

    assert model["input_cost_per_token"] * 1_000_000 == Decimal("1")
    assert model["output_cost_per_token"] * 1_000_000 == Decimal("2")
    assert model["cache_read_input_token_cost"] * 1_000_000 == Decimal("0.1")
    assert model["cache_creation_input_token_cost"] * 1_000_000 == Decimal("1")


@pytest.mark.parametrize("identifier", _MODELS)
def test_explicit_efforts_preserve_full_controls_and_mini_denial(
    identifier: str,
) -> None:
    """The fixture advertises exact controls, independently of prices/profiles."""
    model = _inference_profile_source_payload("baseline")[identifier]
    if identifier == "gpt-5.5-mini":
        assert model["supports_reasoning"] is False
        assert model["reasoning_effort_levels"] == []
        assert model["supports_web_search"] is False
    else:
        assert model["supports_reasoning"] is True
        assert model["reasoning_effort_levels"] == _FULL_EFFORTS
        assert model["supports_web_search"] is True


def test_catalog_payload_generation_does_not_share_mutable_effort_arrays() -> None:
    """Mutation of one caller's JSON data cannot rewrite other model declarations."""
    payload = _inference_profile_source_payload("baseline")
    efforts = payload["gpt-5.5"]["reasoning_effort_levels"]
    assert isinstance(efforts, list)
    efforts.clear()

    assert payload["gpt-6-astra"]["reasoning_effort_levels"] == _FULL_EFFORTS
    assert (
        _inference_profile_source_payload("baseline")["gpt-5.5"][
            "reasoning_effort_levels"
        ]
        == _FULL_EFFORTS
    )


def test_refreshed_source_changes_only_exact_gpt55_effort_and_token_rates() -> None:
    baseline = _inference_profile_source_payload("baseline")
    refreshed = _inference_profile_source_payload("refreshed")
    expected = {
        **baseline["gpt-5.5"],
        "reasoning_effort_levels": [
            effort for effort in _FULL_EFFORTS if effort != "max"
        ],
        "input_cost_per_token": 0.000003,
        "output_cost_per_token": 0.000004,
    }

    assert refreshed == {**baseline, "gpt-5.5": expected}
    assert tuple(refreshed) == _MODELS
    assert _inference_profile_source_payload("baseline") == baseline
    # The served-default stream uses one input token and one output token.
    restored = json.loads(json.dumps(refreshed), parse_float=Decimal)
    assert (
        restored["gpt-5.5"]["input_cost_per_token"]
        + restored["gpt-5.5"]["output_cost_per_token"]
    ) == Decimal("0.000007")
    original = json.loads(json.dumps(baseline), parse_float=Decimal)
    assert (
        original["gpt-5.5"]["input_cost_per_token"]
        + original["gpt-5.5"]["output_cost_per_token"]
    ) == Decimal("0.000003")


def test_missing_model_source_keeps_other_exact_records_unchanged() -> None:
    baseline = _inference_profile_source_payload("baseline")
    missing = _inference_profile_source_payload("missing-model")

    assert missing == {
        identifier: model
        for identifier, model in baseline.items()
        if identifier != "gpt-5.5"
    }
    assert tuple(missing) == _MODELS[1:]


class _SourceControlHandler(proxy._Handler):
    """Exercise only local control/GET dispatch without constructing a listener."""

    def __init__(self, body: bytes) -> None:
        self.path = "/inference-profile/catalog-source"
        self.body = body
        self.status: int | None = None
        self.value: object = None

    def _read_body(self) -> bytes:
        return self.body

    def _write_json(self, status: int, value: object) -> None:
        self.status = status
        self.value = value


@pytest.mark.parametrize("variant", ["baseline", "refreshed", "missing-model"])
def test_source_control_does_not_rearm_or_reset_provider_scenarios(
    monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    """Switching source data is independent of prepared barriers and response tiers."""
    barrier = proxy._ProviderToolLiveBarrier()
    barrier.arm()
    barrier.release()
    monkeypatch.setattr(proxy, "_INFERENCE_PROFILE_BARRIER", barrier)
    monkeypatch.setattr(proxy._State, "catalog_source_variant", "baseline")
    monkeypatch.setattr(proxy._State, "requests", [{"sentinel": "retained"}])
    before_barrier = barrier.evidence()
    before_tiers = proxy._INFERENCE_PROFILE_TIERS.copy()
    handler = _SourceControlHandler(json.dumps({"variant": variant}).encode())

    handler.do_POST()

    assert handler.status == 200
    assert handler.value == {"variant": variant}
    assert proxy._State.catalog_source_variant == variant
    assert barrier.evidence() == before_barrier
    assert proxy._INFERENCE_PROFILE_TIERS == before_tiers
    assert proxy._State.requests == [{"sentinel": "retained"}]
    reader = _SourceControlHandler(b"")
    reader.do_GET()
    assert reader.status == 200
    assert isinstance(reader.value, dict)
    if variant == "missing-model":
        assert "gpt-5.5" not in reader.value
    else:
        expected_efforts = (
            _FULL_EFFORTS
            if variant == "baseline"
            else [effort for effort in _FULL_EFFORTS if effort != "max"]
        )
        assert reader.value["gpt-5.5"]["reasoning_effort_levels"] == expected_efforts


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"variant":null}',
        b'{"variant":"unknown"}',
        b'{"variant":1}',
        b'{"variant":true}',
        b'{"variant":false}',
        b'{"variant":["baseline"]}',
        b'{"variant":{}}',
        b'{"variant":"baseline","armed":true}',
        b'{"variant":',
        b'["baseline"]',
        b"\xff",
    ],
)
def test_invalid_source_controls_fail_without_mutating_source_or_barrier(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr(proxy._State, "catalog_source_variant", "refreshed")
    before_barrier = proxy._INFERENCE_PROFILE_BARRIER.evidence()
    handler = _SourceControlHandler(body)

    handler.do_POST()

    assert handler.status == 400
    assert handler.value == {
        "error": {"message": "A valid catalog source variant is required."}
    }
    assert proxy._State.catalog_source_variant == "refreshed"
    assert proxy._INFERENCE_PROFILE_BARRIER.evidence() == before_barrier
