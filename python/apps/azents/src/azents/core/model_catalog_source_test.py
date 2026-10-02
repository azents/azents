"""Deterministic fixtures for the data-only source boundary."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from azents.core import model_catalog_source
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_catalog_source import (
    CatalogFact,
    CatalogPriceEvidence,
    CatalogPriceNumber,
    CatalogSourceDecodeError,
    CatalogSourceModel,
    CatalogSourcePayload,
    decode_catalog_source,
)


def _model(**fields: object) -> CatalogSourceModel:
    raw = {
        "exact-model": {
            "litellm_provider": "openai",
            "mode": "responses",
            **fields,
        }
    }
    return decode_catalog_source(json.dumps(raw).encode()).models[0]


@pytest.mark.parametrize(
    "value", ["2026-02-30", "20261002", "2026-W40-5", "", "tomorrow", 20261002]
)
def test_consumed_lifecycle_date_is_validated_before_source_publication(
    value: object,
) -> None:
    with pytest.raises(CatalogSourceDecodeError):
        _model(deprecation_date=value)


def test_lifecycle_date_is_validated_on_strict_snapshot_restore() -> None:
    payload = decode_catalog_source(
        b'{"m":{"litellm_provider":"openai","deprecation_date":"2026-10-02"}}'
    )
    assert payload.models[0].facts.deprecation_date.value == "2026-10-02"
    stored = payload.model_dump_json()
    with pytest.raises(ValidationError):
        CatalogSourcePayload.model_validate_json(
            stored.replace("2026-10-02", "2026-02-30")
        )


def test_counts_exclude_nonmodels_and_lookup_is_literal_and_scoped() -> None:
    payload = decode_catalog_source(
        b"""{
          "sample_spec": {"max_tokens": "documentation"},
          "fallback_generalizations": {"rules": [{"pattern": ".*"}]},
          "openrouter/publisher/model": {"litellm_provider": "openrouter"},
          "native/model": {"litellm_provider": "openai"}
        }"""
    )

    assert payload.model_count == 2
    assert payload.provider_count == 2
    assert payload.lookup_exact(provider="openai", model_key="native/model") is not None
    assert payload.lookup_exact(provider="openai", model_key="model") is None
    assert payload.lookup_exact(provider="chatgpt", model_key="native/model") is None
    assert (
        payload.lookup_exact(
            provider="openrouter", model_key="openrouter/publisher/model"
        )
        is not None
    )
    assert (
        payload.lookup_exact(provider="openrouter", model_key="publisher/model") is None
    )


def test_undeclared_alias_contract_does_not_create_lookup_identity() -> None:
    payload = decode_catalog_source(
        b'{"literal":{"litellm_provider":"openai","aliases":["other"]}}'
    )
    assert payload.lookup_exact(provider="openai", model_key="other") is None
    assert payload.models[0].extensions_json == '{"aliases":["other"]}'


def test_canonical_roundtrip_preserves_presence_and_hash() -> None:
    first = decode_catalog_source(
        b"""{
          "z": {"supports_reasoning": null, "litellm_provider": "xai"},
          "a": {"litellm_provider": "openai", "supports_web_search": false,
                "supported_modalities": [], "max_input_tokens": 0}
        }"""
    )
    reordered = decode_catalog_source(
        b'{"a":{"max_input_tokens":0,"supported_modalities":[],'
        b'"supports_web_search":false,"litellm_provider":"openai"},'
        b'"z":{"litellm_provider":"xai","supports_reasoning":null}}'
    )
    restored = CatalogSourcePayload.model_validate_json(first.model_dump_json())
    assert first.content_hash == reordered.content_hash == restored.content_hash
    assert restored.models[0].facts.reasoning.state == "absent"
    assert restored.models[0].facts.web_search.value is False
    assert restored.models[0].facts.input_modalities.value == ()
    assert restored.models[0].facts.max_input_tokens.value == 0
    assert restored.models[1].facts.reasoning.state == "null"
    assert restored.model_dump(mode="json") == first.model_dump(mode="json")


def test_same_source_key_in_different_provider_is_not_a_match() -> None:
    payload = decode_catalog_source(b'{"m":{"litellm_provider":"bedrock"}}')
    assert payload.lookup_exact(provider="anthropic", model_key="m") is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"{}",
        b'{"sample_spec":{}}',
        b'{"m":{"mode":"chat"}}',
        b'{"m":{"litellm_provider":null}}',
        b'{"m":{"litellm_provider":" openai"}}',
        b'{" m":{"litellm_provider":"openai"}}',
        b'{"m":null}',
        b'{"m":{"litellm_provider":"openai"},"m":{"litellm_provider":"xai"}}',
        b'{"m":{"litellm_provider":"openai","nested":{"x":1,"x":2}}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":NaN}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":Infinity}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":-0.1}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":true}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":"0.1"}}',
        b'{"m":{"litellm_provider":"openai","input_cost_per_token":1e1001}}',
        b'{"m":{"litellm_provider":"openai","supports_reasoning":1}}',
        b'{"m":{"litellm_provider":"openai","supports_reasoning":"true"}}',
        b'{"m":{"litellm_provider":"openai","max_input_tokens":true}}',
        b'{"m":{"litellm_provider":"openai","max_input_tokens":-1}}',
        b'{"m":{"litellm_provider":"openai","max_input_tokens":1.1}}',
        b'{"m":{"litellm_provider":"openai","reasoning_effort_levels":"high"}}',
        b'{"m":{"litellm_provider":"openai","reasoning_effort_levels":["bogus"]}}',
        b'{"m":{"litellm_provider":"openai","supported_modalities":[null]}}',
        b'{"m":{"litellm_provider":"openai","extension":"\\ud800"}}',
        b"\xff",
    ],
)
def test_invalid_source_rejects_without_a_partial_payload(raw: bytes) -> None:
    with pytest.raises(CatalogSourceDecodeError):
        decode_catalog_source(raw)


def test_byte_and_nesting_limits_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_catalog_source, "CATALOG_SOURCE_MAX_BYTES", 32)
    with pytest.raises(CatalogSourceDecodeError, match="byte size"):
        decode_catalog_source(b" " * 33)
    monkeypatch.setattr(model_catalog_source, "CATALOG_SOURCE_MAX_BYTES", 4096)
    nested = b"[" * 66 + b"0" + b"]" * 66
    with pytest.raises(CatalogSourceDecodeError, match="nesting"):
        decode_catalog_source(
            b'{"m":{"litellm_provider":"openai","extension":' + nested + b"}}"
        )


def test_model_limit_excludes_documentation_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_catalog_source, "_MAX_MODELS", 1)
    with pytest.raises(CatalogSourceDecodeError, match="bounded model"):
        decode_catalog_source(
            b'{"a":{"litellm_provider":"openai"},"b":{"litellm_provider":"openai"}}'
        )


def test_duplicate_restored_identity_is_rejected() -> None:
    item = _model()
    with pytest.raises(ValidationError, match="Duplicate exact"):
        CatalogSourcePayload(
            schema_version="1", interpreter_version="1", models=(item, item)
        )


def test_presence_wrapper_cannot_lie_about_null_or_absence() -> None:
    with pytest.raises(ValidationError, match="presence"):
        CatalogFact[bool](state="absent", value=False)
    with pytest.raises(ValidationError, match="presence"):
        CatalogFact[bool](state="value", value=None)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"supports_reasoning": True},
        {"supports_reasoning": None},
        {
            "supports_reasoning": True,
            "supports_xhigh_reasoning_effort": None,
            "supports_low_reasoning_effort": None,
        },
    ],
)
def test_no_effort_evidence_never_manufactures_a_list(
    fields: dict[str, object],
) -> None:
    model = _model(**fields)
    assert model.reasoning.supported_efforts == ()
    assert model.reasoning.complete is False
    assert all(level.support == "unknown" for level in model.reasoning.levels)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"supports_xhigh_reasoning_effort": False},
        {"reasoning_effort_levels": []},
        {"reasoning_effort_levels": ["max"]},
        {"supports_max_reasoning_effort": True},
    ],
)
def test_reasoning_denial_is_terminal_before_array_and_flags(
    fields: dict[str, object],
) -> None:
    model = _model(supports_reasoning=False, **fields)
    assert model.reasoning.supported_efforts == ()
    assert model.reasoning.complete
    assert all(level.support == "unsupported" for level in model.reasoning.levels)
    positive = bool(fields.get("reasoning_effort_levels")) or fields.get(
        "supports_max_reasoning_effort"
    )
    assert bool(model.reasoning.diagnostics) == bool(positive)


@pytest.mark.parametrize("efforts", [[], ["max", "low", "high", "low"]])
def test_explicit_array_wins_over_flags_without_inventing_baseline(
    efforts: list[str],
) -> None:
    model = _model(
        supports_reasoning=True,
        reasoning_effort_levels=efforts,
        supports_xhigh_reasoning_effort=True,
        supports_low_reasoning_effort=False,
    )
    expected = tuple(level for level in ModelReasoningEffort if level in efforts)
    assert model.reasoning.supported_efforts == expected
    assert model.reasoning.complete
    assert model.reasoning.origin == "explicit"
    assert model.facts.reasoning.value is True


def test_null_array_does_not_fall_through_to_flag_defaults() -> None:
    model = _model(
        supports_reasoning=True,
        reasoning_effort_levels=None,
        supports_max_reasoning_effort=True,
    )
    assert model.facts.reasoning_efforts.state == "null"
    assert model.reasoning.complete is False
    assert model.reasoning.supported_efforts == ()


def test_scoped_flag_contract_preserves_explicit_and_derived_origins() -> None:
    model = _model(
        supports_reasoning=True,
        supports_xhigh_reasoning_effort=True,
        supports_minimal_reasoning_effort=False,
        supports_max_reasoning_effort=None,
    )
    assert model.reasoning.supported_efforts == (
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
    )
    by_level = {item.level: item for item in model.reasoning.levels}
    assert by_level[ModelReasoningEffort.NONE].origin == "source_contract"
    assert by_level[ModelReasoningEffort.XHIGH].origin == "explicit"
    assert by_level[ModelReasoningEffort.MINIMAL].support == "unsupported"
    assert by_level[ModelReasoningEffort.MAX].support == "unknown"
    assert not model.reasoning.complete
    assert model.facts.default_reasoning_effort.state == "absent"


def test_negative_flag_gates_contract_but_does_not_rewrite_raw_reasoning_null() -> None:
    model = _model(supports_reasoning=None, supports_xhigh_reasoning_effort=False)
    assert model.facts.reasoning.state == "null"
    assert model.reasoning.complete
    assert ModelReasoningEffort.MEDIUM in model.reasoning.supported_efforts
    assert ModelReasoningEffort.XHIGH not in model.reasoning.supported_efforts
    assert ModelReasoningEffort.MAX not in model.reasoning.supported_efforts


@pytest.mark.parametrize(
    "provider", ["azure", "bedrock", "xai", "openrouter", "moonshot"]
)
def test_native_flag_defaults_are_not_transferred_to_other_hosts(provider: str) -> None:
    model = _model(
        litellm_provider=provider,
        supports_reasoning=True,
        supports_xhigh_reasoning_effort=True,
    )
    assert model.reasoning.supported_efforts == (ModelReasoningEffort.XHIGH,)
    assert not model.reasoning.complete


@pytest.mark.parametrize("endpoints", [[], None, ["/v1/chat/completions"]])
def test_unknown_or_denied_native_endpoint_does_not_get_defaults(
    endpoints: list[str] | None,
) -> None:
    model = _model(
        supported_endpoints=endpoints,
        supports_xhigh_reasoning_effort=True,
    )
    assert model.reasoning.supported_efforts == (ModelReasoningEffort.XHIGH,)
    assert not model.reasoning.complete


@pytest.mark.parametrize("provider", ["openai", "chatgpt"])
def test_explicit_responses_route_allows_the_native_contract(provider: str) -> None:
    model = _model(
        litellm_provider=provider,
        mode="chat",
        supported_endpoints=["/v1/responses"],
        supports_none_reasoning_effort=False,
    )
    assert model.reasoning.complete
    assert model.reasoning.supported_efforts == (
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    )


def test_sampling_and_strict_tool_support_are_not_inferred() -> None:
    model = _model(
        supports_reasoning=True,
        supports_none_reasoning_effort=True,
        default_reasoning_effort="none",
        supports_response_schema=True,
    )
    assert model.facts.sampling.state == "absent"
    assert model.facts.bedrock_strict_tools.state == "absent"
    assert model.facts.response_schema.value is True
    assert model.facts.default_reasoning_effort.value is ModelReasoningEffort.NONE


def test_price_lexemes_units_and_unknown_dimensions_survive_roundtrip() -> None:
    payload = decode_catalog_source(
        b"""{"m": {
          "litellm_provider":"openai",
          "input_cost_per_token": 1.2500e-07,
          "output_cost_per_token": 0,
          "cache_read_input_token_cost": null,
          "unknown_future_cost_rule": {"dimensions": ["region"], "rate": 0.01230},
          "off_peak_pricing": {
            "hours_utc": "22:00-02:00", "input_cost_per_token": 1e-8
          },
          "currency": "USD"
        }}"""
    )
    restored = CatalogSourcePayload.model_validate_json(payload.model_dump_json())
    evidence = {item.source_field: item for item in restored.models[0].price_evidence}
    rate = evidence["input_cost_per_token"].number
    assert rate is not None
    assert rate.lexeme == "1.2500e-07"
    assert rate.token_kind == "decimal"
    assert rate.decimal_value == Decimal("0.000000125")
    assert evidence["output_cost_per_token"].number is not None
    assert evidence["cache_read_input_token_cost"].kind == "null"
    assert evidence["unknown_future_cost_rule"].kind == "structured"
    assert "0.01230" in evidence["unknown_future_cost_rule"].encoded_value
    assert evidence["off_peak_pricing"].kind == "structured"
    assert evidence["currency"].encoded_value == '"USD"'
    assert restored.content_hash == payload.content_hash


def test_capabilities_never_derive_from_price_or_unknown_extensions() -> None:
    model = _model(
        search_context_cost_per_query={"search_context_size_low": 0.01},
        arbitrary_parameter_configuration={"temperature": 1},
    )
    assert model.facts.web_search.state == "absent"
    assert model.facts.sampling.state == "absent"
    assert model.extensions_json == (
        '{"arbitrary_parameter_configuration":{"temperature":1}}'
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("facts", "reasoning", "value"), "true"),
        (("facts", "reasoning", "value"), 1),
        (("facts", "max_input_tokens", "value"), "100"),
        (("facts", "max_input_tokens", "value"), True),
        (("facts", "max_input_tokens", "value"), -1),
        (("facts", "max_input_tokens", "value"), 2**63),
        (("facts", "supported_endpoints", "value"), ["/v1/responses"] * 257),
        (("reasoning", "levels", 0, "support"), "supported"),
        (("reasoning", "levels", 0, "origin"), "source_contract"),
        (("reasoning", "complete"), False),
        (("reasoning", "complete"), "true"),
        (("reasoning", "diagnostics"), ["fabricated"]),
        (("source_key",), " malformed "),
        (("source_key",), "sample_spec"),
        (("source_key",), "x" * 2049),
        (("provider",), ""),
        (("price_evidence", 0, "number", "lexeme"), "-Infinity"),
        (("price_evidence", 0, "number", "lexeme"), "-0.1"),
        (("price_evidence", 0, "number", "token_kind"), "integer"),
        (("price_evidence", 0, "encoded_value"), "0.0001"),
        (("price_evidence", 0, "kind"), "null"),
        (("price_evidence", 0, "number"), None),
        (("extensions_json",), '{"supports_reasoning":true}'),
        (("extensions_json",), '{"unknown_future_cost":0}'),
        (("extensions_json",), '{"note":"ok","note":"duplicate"}'),
        (("extensions_json",), "[]"),
        (("extensions_json",), "{}"),
    ],
)
def test_persisted_snapshot_rejects_incoherent_or_coercible_facts(
    path: tuple[str | int, ...], value: object
) -> None:
    payload = decode_catalog_source(
        b'{"m":{"litellm_provider":"openai","supports_reasoning":false,'
        b'"max_input_tokens":100,"supported_endpoints":["/v1/responses"],'
        b'"input_cost_per_token":1e-7,"note":"ok"}}'
    )
    document = json.loads(payload.model_dump_json())
    target = document["models"][0]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        CatalogSourcePayload.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    ("lexeme", "kind"),
    [
        ("NaN", "decimal"),
        ("Infinity", "decimal"),
        ("-Infinity", "decimal"),
        ("-1", "integer"),
        ("+1", "integer"),
        ("01", "integer"),
        (".1", "decimal"),
        ("1.", "decimal"),
        (" 1", "integer"),
        ("1_000", "integer"),
        ("1", "decimal"),
        ("1.0", "integer"),
        ("1e0", "integer"),
        ("1e1001", "decimal"),
        ("1" * 129, "integer"),
    ],
)
def test_persisted_price_numbers_validate_grammar_kind_and_domain(
    lexeme: str, kind: str
) -> None:
    with pytest.raises(ValidationError):
        CatalogPriceNumber.model_validate_json(
            json.dumps({"lexeme": lexeme, "token_kind": kind})
        )


@pytest.mark.parametrize("efforts", [["high", "low"], ["low", "low"]])
def test_persisted_effort_array_requires_unique_canonical_order(
    efforts: list[str],
) -> None:
    model = _model(reasoning_effort_levels=["low", "high"])
    document = model.model_dump(mode="json")
    document["facts"]["reasoning_efforts"]["value"] = efforts
    with pytest.raises(ValidationError, match="not canonical"):
        CatalogSourceModel.model_validate_json(json.dumps(document))


def test_persisted_payload_enforces_model_bounds_and_price_key_uniqueness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = decode_catalog_source(
        b'{"a":{"litellm_provider":"openai","input_cost_per_token":0},'
        b'"b":{"litellm_provider":"openai"}}'
    )
    document = payload.model_dump(mode="json")
    prices = document["models"][0]["price_evidence"]
    prices.append(prices[0])
    with pytest.raises(ValidationError, match="price evidence keys"):
        CatalogSourcePayload.model_validate_json(json.dumps(document))
    with pytest.raises(ValidationError, match="bounded model"):
        CatalogSourcePayload.model_validate_json(
            '{"schema_version":"1","interpreter_version":"1","models":[]}'
        )
    monkeypatch.setattr(model_catalog_source, "_MAX_MODELS", 1)
    with pytest.raises(ValidationError, match="bounded model"):
        CatalogSourcePayload.model_validate_json(payload.model_dump_json())


@pytest.mark.parametrize(
    ("field", "kind", "encoded"),
    [
        ("cache_read_input_token_cost", "null", "0"),
        ("off_peak_pricing", "structured", '"text"'),
        ("off_peak_pricing", "structured", '{"x":NaN}'),
        ("currency", "text", "0"),
        ("input_cost_per_token", "text", '"0.1"'),
    ],
)
def test_persisted_price_kind_matches_encoded_evidence(
    field: str, kind: str, encoded: str
) -> None:
    with pytest.raises(ValidationError):
        CatalogPriceEvidence.model_validate_json(
            json.dumps(
                {
                    "source_field": field,
                    "kind": kind,
                    "number": None,
                    "encoded_value": encoded,
                }
            )
        )
