"""Data-only catalog ingestion with exact identities and presence-aware facts."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from azents.core.llm_catalog import ModelReasoningEffort

CATALOG_SOURCE_KEY = "litellm_catalog"
CATALOG_SOURCE_KIND = "litellm_json"
CATALOG_SOURCE_SCHEMA_VERSION = "1"
CATALOG_SOURCE_INTERPRETER_VERSION = "1"
CATALOG_SOURCE_MAX_BYTES = 12 * 1024 * 1024
_MAX_MODELS = 20_000
_MAX_DEPTH = 64
_MAX_IDENTIFIER_LENGTH = 2048
_NON_MODEL_KEYS = frozenset({"sample_spec", "fallback_generalizations"})
_EFFORT_ORDER = tuple(ModelReasoningEffort)
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


class CatalogSourceDecodeError(ValueError):
    """Reject a source document without publishing partial evidence."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CatalogFact[T](_FrozenModel):
    """One source declaration, preserving omission across JSON round trips."""

    state: Literal["absent", "null", "value"]
    value: T | None

    @model_validator(mode="after")
    def validate_presence(self) -> CatalogFact[T]:
        """Require a value exactly when the declaration has a valid value."""
        if (self.state == "value") != (self.value is not None):
            raise ValueError("Source fact presence and value disagree.")
        return self


class CatalogSourceFacts(_FrozenModel):
    """Descriptive declarations, independent of runtime authorization."""

    mode: CatalogFact[str]
    display_name: CatalogFact[str]
    deprecation_date: CatalogFact[str]
    supported_endpoints: CatalogFact[tuple[str, ...]]
    input_modalities: CatalogFact[tuple[str, ...]]
    output_modalities: CatalogFact[tuple[str, ...]]
    max_input_tokens: CatalogFact[int]
    max_output_tokens: CatalogFact[int]
    legacy_max_tokens: CatalogFact[int]
    function_calling: CatalogFact[bool]
    parallel_function_calling: CatalogFact[bool]
    response_schema: CatalogFact[bool]
    native_structured_output: CatalogFact[bool]
    bedrock_strict_tools: CatalogFact[bool]
    vision: CatalogFact[bool]
    image_input: CatalogFact[bool]
    pdf_input: CatalogFact[bool]
    audio_input: CatalogFact[bool]
    audio_output: CatalogFact[bool]
    video_input: CatalogFact[bool]
    web_search: CatalogFact[bool]
    sampling: CatalogFact[bool]
    reasoning: CatalogFact[bool]
    reasoning_efforts: CatalogFact[tuple[ModelReasoningEffort, ...]]
    default_reasoning_effort: CatalogFact[ModelReasoningEffort]
    none_effort: CatalogFact[bool]
    minimal_effort: CatalogFact[bool]
    low_effort: CatalogFact[bool]
    xhigh_effort: CatalogFact[bool]
    max_effort: CatalogFact[bool]

    @model_validator(mode="after")
    def validate_domain_bounds(self) -> CatalogSourceFacts:
        """Keep restored facts within the same domain as freshly decoded facts."""
        if self.deprecation_date.value is not None:
            _date_string(self.deprecation_date.value)
        for fact in (
            self.max_input_tokens,
            self.max_output_tokens,
            self.legacy_max_tokens,
        ):
            if fact.value is not None and not 0 <= fact.value <= 2**63 - 1:
                raise ValueError("Source token limit is out of bounds.")
        for fact in (
            self.supported_endpoints,
            self.input_modalities,
            self.output_modalities,
        ):
            if fact.value is not None and len(fact.value) > 256:
                raise ValueError("Source declaration array is too long.")
        efforts = self.reasoning_efforts.value
        if efforts is not None and efforts != tuple(
            level for level in _EFFORT_ORDER if level in efforts
        ):
            raise ValueError("Source effort array is not canonical.")
        return self


class CatalogEffortEvidence(_FrozenModel):
    """One advertised level and whether its meaning is explicit or derived."""

    level: ModelReasoningEffort
    support: Literal["supported", "unsupported", "unknown"]
    origin: Literal["explicit", "source_contract", "unknown"]


class CatalogReasoningEvidence(_FrozenModel):
    """Interpreted effort facts, not a request policy or model availability."""

    levels: tuple[CatalogEffortEvidence, ...]
    complete: bool
    origin: Literal["explicit", "source_contract", "unknown"]
    diagnostics: tuple[str, ...]

    @property
    def supported_efforts(self) -> tuple[ModelReasoningEffort, ...]:
        """Return only individually justified levels, possibly an incomplete set."""
        return tuple(item.level for item in self.levels if item.support == "supported")


class CatalogPriceNumber(_FrozenModel):
    """A source numeric lexeme retained without binary floating-point rounding."""

    lexeme: str
    token_kind: Literal["integer", "decimal"]

    @model_validator(mode="after")
    def validate_number(self) -> CatalogPriceNumber:
        """Validate numeric syntax and meaning on restored source evidence."""
        _number_token(self.lexeme, self.token_kind)
        if Decimal(self.lexeme) < 0:
            raise ValueError("Source price cannot be negative.")
        return self

    @property
    def decimal_value(self) -> Decimal:
        """Read the preserved rate without changing its unit."""
        return Decimal(self.lexeme)


class CatalogPriceEvidence(_FrozenModel):
    """Bounded ingestion evidence; phase-specific price interpretation is separate."""

    source_field: str
    kind: Literal["number", "null", "structured", "text"]
    number: CatalogPriceNumber | None
    encoded_value: str

    @model_validator(mode="after")
    def validate_evidence(self) -> CatalogPriceEvidence:
        """Reject inconsistent encoded and typed views of the same price fact."""
        _identity(self.source_field)
        if not _price_field(self.source_field):
            raise ValueError("Source price field is not a pricing declaration.")
        if self.kind == "number":
            if self.number is None or self.encoded_value != self.number.lexeme:
                raise ValueError("Source price number and encoded value disagree.")
            return self
        if self.number is not None:
            raise ValueError("Only numeric price evidence may contain a number.")
        if self.kind == "null":
            if self.encoded_value != "null":
                raise ValueError("Null price evidence must encode null.")
            return self
        value = _validate_opaque_json(self.encoded_value)
        if self.kind == "structured":
            if not isinstance(value, dict | list):
                raise ValueError("Structured price evidence must encode a container.")
        elif not isinstance(value, str) or (
            "cost" in self.source_field or "multiplier" in self.source_field
        ):
            raise ValueError("Invalid textual price evidence.")
        return self


class CatalogSourceModel(_FrozenModel):
    """One exact source key within its declared hosting/API namespace."""

    source_key: str
    provider: str
    facts: CatalogSourceFacts
    reasoning: CatalogReasoningEvidence
    price_evidence: tuple[CatalogPriceEvidence, ...]
    extensions_json: str | None

    @model_validator(mode="after")
    def validate_model_evidence(self) -> CatalogSourceModel:
        """Require identities, derived facts and opaque evidence to remain coherent."""
        _identity(self.source_key)
        _identity(self.provider)
        if self.source_key in _NON_MODEL_KEYS:
            raise ValueError("Documentation entries are not source models.")
        if self.reasoning != _interpret_reasoning(
            provider=self.provider, facts=self.facts
        ):
            raise ValueError("Source reasoning evidence disagrees with source facts.")
        price_keys = tuple(item.source_field for item in self.price_evidence)
        if price_keys != tuple(sorted(set(price_keys))):
            raise ValueError("Source price evidence keys are not canonical.")
        if self.extensions_json is not None:
            extensions = _object(_validate_opaque_json(self.extensions_json))
            if not extensions or any(
                key == "litellm_provider"
                or key in _FACT_SOURCE_KEYS
                or _price_field(key)
                for key in extensions
            ):
                raise ValueError("Opaque source extensions overlap consumed facts.")
        return self


class CatalogSourcePayload(_FrozenModel):
    """Canonical snapshot payload; document transport metadata is stored separately."""

    schema_version: Literal["1"]
    interpreter_version: Literal["1"]
    models: tuple[CatalogSourceModel, ...]

    @model_validator(mode="after")
    def validate_identities(self) -> CatalogSourcePayload:
        """Reject ambiguous exact identities, including restored snapshots."""
        if not 0 < len(self.models) <= _MAX_MODELS:
            raise ValueError("Source must contain bounded model records.")
        identities = [(model.provider, model.source_key) for model in self.models]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate exact catalog identity.")
        if identities != sorted(identities):
            raise ValueError("Catalog records must have canonical identity order.")
        return self

    @property
    def model_count(self) -> int:
        """Count actual model records rather than documentation/rule entries."""
        return len(self.models)

    @property
    def provider_count(self) -> int:
        """Count exact source namespaces without joining related hosts."""
        return len({model.provider for model in self.models})

    @property
    def content_hash(self) -> str:
        """Hash canonical JSON-safe evidence, independent of document formatting."""
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def lookup_exact(
        self, *, provider: str, model_key: str
    ) -> CatalogSourceModel | None:
        """Look up a literal source key, not a runtime-normalized model identifier.

        :param provider: exact source hosting/API namespace
        :param model_key: literal top-level source key, including any publisher path
        :returns: matching record, or no source evidence
        """
        return next(
            (
                model
                for model in self.models
                if model.provider == provider and model.source_key == model_key
            ),
            None,
        )


@dataclasses.dataclass(frozen=True)
class _NumberToken:
    """Numeric ingress token; never leaves the decoding boundary."""

    lexeme: str
    kind: Literal["integer", "decimal"]


def _number_token(lexeme: str, kind: Literal["integer", "decimal"]) -> _NumberToken:
    if len(lexeme) > 128:
        raise CatalogSourceDecodeError("Source numeric token is too long.")
    if _JSON_NUMBER.fullmatch(lexeme) is None:
        raise CatalogSourceDecodeError("Invalid JSON numeric lexeme.")
    decimal_syntax = any(character in lexeme for character in ".eE")
    if (kind == "decimal") != decimal_syntax:
        raise CatalogSourceDecodeError(
            "Source number token kind disagrees with syntax."
        )
    try:
        value = Decimal(lexeme)
    except InvalidOperation as exc:
        raise CatalogSourceDecodeError("Invalid source numeric token.") from exc
    if not value.is_finite() or abs(value.adjusted()) > 1000:
        raise CatalogSourceDecodeError("Source numeric token is out of bounds.")
    return _NumberToken(lexeme=lexeme, kind=kind)


def _parse_integer(lexeme: str) -> _NumberToken:
    return _number_token(lexeme, "integer")


def _parse_decimal(lexeme: str) -> _NumberToken:
    return _number_token(lexeme, "decimal")


def _reject_constant(_value: str) -> object:
    raise CatalogSourceDecodeError("Non-finite JSON numbers are not accepted.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogSourceDecodeError("Duplicate JSON object key.")
        result[key] = value
    return result


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CatalogSourceDecodeError("Expected a source JSON object.")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CatalogSourceDecodeError("Expected a string object key.")
        result[key] = item
    return result


def _encoded_json(value: object, depth: int = 0) -> str:
    """Canonicalize opaque ingress JSON while preserving number lexemes."""
    if depth > _MAX_DEPTH:
        raise CatalogSourceDecodeError("Source JSON nesting is too deep.")
    if isinstance(value, _NumberToken):
        return value.lexeme
    if value is None or isinstance(value, str | bool):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, list):
        return "[" + ",".join(_encoded_json(v, depth + 1) for v in value) + "]"
    if isinstance(value, dict):
        obj = _object(value)
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False)
                + ":"
                + _encoded_json(obj[key], depth + 1)
                for key in sorted(obj)
            )
            + "}"
        )
    raise CatalogSourceDecodeError("Invalid source JSON value.")


def _validate_opaque_json(encoded: str) -> object:
    """Validate bounded opaque JSON syntax, without interpreting catalog rules."""
    try:
        if not encoded or len(encoded.encode("utf-8")) > CATALOG_SOURCE_MAX_BYTES:
            raise ValueError("Opaque source evidence size is out of bounds.")
        value: object = json.loads(
            encoded,
            object_pairs_hook=_unique_object,
            parse_int=_parse_integer,
            parse_float=_parse_decimal,
            parse_constant=_reject_constant,
        )
        if _encoded_json(value) != encoded:
            raise ValueError("Opaque source evidence is not canonical JSON.")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid opaque source JSON evidence.") from exc


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise CatalogSourceDecodeError("Expected a source string.")
    return value


def _date_string(value: object) -> str:
    """Consume only an exact calendar date for lifecycle decisions."""
    text = _string(value)
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError:
        raise CatalogSourceDecodeError("Invalid source calendar date.") from None
    if parsed.isoformat() != text:
        raise CatalogSourceDecodeError("Source calendar date must use YYYY-MM-DD.")
    return text


def _identity(value: object) -> str:
    text = _string(value)
    if (
        not text
        or text != text.strip()
        or len(text) > _MAX_IDENTIFIER_LENGTH
        or any(ord(char) < 32 for char in text)
    ):
        raise CatalogSourceDecodeError("Invalid exact source identity.")
    return text


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise CatalogSourceDecodeError("Expected a source boolean.")
    return value


def _count(value: object) -> int:
    if not isinstance(value, _NumberToken) or value.kind != "integer":
        raise CatalogSourceDecodeError("Expected a source integer token limit.")
    number = int(value.lexeme)
    if not 0 <= number <= 2**63 - 1:
        raise CatalogSourceDecodeError("Source token limit is out of bounds.")
    return number


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 256:
        raise CatalogSourceDecodeError("Expected a bounded source string array.")
    return tuple(_string(item) for item in value)


def _effort(value: object) -> ModelReasoningEffort:
    try:
        return ModelReasoningEffort(_string(value))
    except ValueError as exc:
        raise CatalogSourceDecodeError("Invalid source reasoning effort.") from exc


def _efforts(value: object) -> tuple[ModelReasoningEffort, ...]:
    values = {_effort(item) for item in _strings(value)}
    return tuple(level for level in _EFFORT_ORDER if level in values)


def _fact[T](
    raw: Mapping[str, object], key: str, decode: Callable[[object], T]
) -> CatalogFact[T]:
    if key not in raw:
        return CatalogFact[T](state="absent", value=None)
    if raw[key] is None:
        return CatalogFact[T](state="null", value=None)
    return CatalogFact[T](state="value", value=decode(raw[key]))


def _decode_facts(raw: Mapping[str, object]) -> CatalogSourceFacts:
    return CatalogSourceFacts(
        mode=_fact(raw, "mode", _string),
        display_name=_fact(raw, "display_name", _string),
        deprecation_date=_fact(raw, "deprecation_date", _date_string),
        supported_endpoints=_fact(raw, "supported_endpoints", _strings),
        input_modalities=_fact(raw, "supported_modalities", _strings),
        output_modalities=_fact(raw, "supported_output_modalities", _strings),
        max_input_tokens=_fact(raw, "max_input_tokens", _count),
        max_output_tokens=_fact(raw, "max_output_tokens", _count),
        legacy_max_tokens=_fact(raw, "max_tokens", _count),
        function_calling=_fact(raw, "supports_function_calling", _boolean),
        parallel_function_calling=_fact(
            raw, "supports_parallel_function_calling", _boolean
        ),
        response_schema=_fact(raw, "supports_response_schema", _boolean),
        native_structured_output=_fact(
            raw, "supports_native_structured_output", _boolean
        ),
        bedrock_strict_tools=_fact(
            raw, "bedrock_converse_supports_strict_tools", _boolean
        ),
        vision=_fact(raw, "supports_vision", _boolean),
        image_input=_fact(raw, "supports_image_input", _boolean),
        pdf_input=_fact(raw, "supports_pdf_input", _boolean),
        audio_input=_fact(raw, "supports_audio_input", _boolean),
        audio_output=_fact(raw, "supports_audio_output", _boolean),
        video_input=_fact(raw, "supports_video_input", _boolean),
        web_search=_fact(raw, "supports_web_search", _boolean),
        sampling=_fact(raw, "supports_sampling_params", _boolean),
        reasoning=_fact(raw, "supports_reasoning", _boolean),
        reasoning_efforts=_fact(raw, "reasoning_effort_levels", _efforts),
        default_reasoning_effort=_fact(raw, "default_reasoning_effort", _effort),
        none_effort=_fact(raw, "supports_none_reasoning_effort", _boolean),
        minimal_effort=_fact(raw, "supports_minimal_reasoning_effort", _boolean),
        low_effort=_fact(raw, "supports_low_reasoning_effort", _boolean),
        xhigh_effort=_fact(raw, "supports_xhigh_reasoning_effort", _boolean),
        max_effort=_fact(raw, "supports_max_reasoning_effort", _boolean),
    )


def _unknown_level(level: ModelReasoningEffort) -> CatalogEffortEvidence:
    return CatalogEffortEvidence(level=level, support="unknown", origin="unknown")


def _interpret_reasoning(
    *, provider: str, facts: CatalogSourceFacts
) -> CatalogReasoningEvidence:
    flags = {
        ModelReasoningEffort.NONE: facts.none_effort,
        ModelReasoningEffort.MINIMAL: facts.minimal_effort,
        ModelReasoningEffort.LOW: facts.low_effort,
        ModelReasoningEffort.XHIGH: facts.xhigh_effort,
        ModelReasoningEffort.MAX: facts.max_effort,
    }
    if facts.reasoning.value is False:
        conflict = bool(facts.reasoning_efforts.value) or any(
            flag.value is True for flag in flags.values()
        )
        return CatalogReasoningEvidence(
            levels=tuple(
                CatalogEffortEvidence(
                    level=level, support="unsupported", origin="explicit"
                )
                for level in _EFFORT_ORDER
            ),
            complete=True,
            origin="explicit",
            diagnostics=("reasoning_denial_conflict",) if conflict else (),
        )
    declared = facts.reasoning_efforts
    if declared.state == "value":
        return CatalogReasoningEvidence(
            levels=tuple(
                CatalogEffortEvidence(
                    level=level,
                    support=(
                        "supported"
                        if level in (declared.value or ())
                        else "unsupported"
                    ),
                    origin="explicit",
                )
                for level in _EFFORT_ORDER
            ),
            complete=True,
            origin="explicit",
            diagnostics=(),
        )
    if declared.state == "null":
        return CatalogReasoningEvidence(
            levels=tuple(_unknown_level(level) for level in _EFFORT_ORDER),
            complete=False,
            origin="unknown",
            diagnostics=(),
        )

    has_flag = any(flag.state == "value" for flag in flags.values())
    endpoint = facts.supported_endpoints
    # A declared endpoint denial cannot be overridden by a generic mode label.
    responses = (
        "/v1/responses" in (endpoint.value or ())
        if endpoint.state == "value"
        else endpoint.state == "absent" and facts.mode.value == "responses"
    )
    derive = has_flag and provider in {"openai", "chatgpt"} and responses
    levels: list[CatalogEffortEvidence] = []
    for level in _EFFORT_ORDER:
        flag = flags.get(level)
        if flag is not None and flag.state == "value":
            levels.append(
                CatalogEffortEvidence(
                    level=level,
                    support="supported" if flag.value else "unsupported",
                    origin="explicit",
                )
            )
        elif derive and (flag is None or flag.state == "absent"):
            levels.append(
                CatalogEffortEvidence(
                    level=level,
                    support=(
                        "unsupported"
                        if level
                        in {ModelReasoningEffort.XHIGH, ModelReasoningEffort.MAX}
                        else "supported"
                    ),
                    origin="source_contract",
                )
            )
        else:
            levels.append(_unknown_level(level))
    return CatalogReasoningEvidence(
        levels=tuple(levels),
        complete=all(item.support != "unknown" for item in levels),
        origin="source_contract" if derive else "explicit" if has_flag else "unknown",
        diagnostics=(),
    )


_FACT_SOURCE_KEYS = frozenset(
    {
        "mode",
        "display_name",
        "deprecation_date",
        "supported_endpoints",
        "supported_modalities",
        "supported_output_modalities",
        "max_input_tokens",
        "max_output_tokens",
        "max_tokens",
        "supports_function_calling",
        "supports_parallel_function_calling",
        "supports_response_schema",
        "supports_native_structured_output",
        "bedrock_converse_supports_strict_tools",
        "supports_vision",
        "supports_image_input",
        "supports_pdf_input",
        "supports_audio_input",
        "supports_audio_output",
        "supports_video_input",
        "supports_web_search",
        "supports_sampling_params",
        "supports_reasoning",
        "reasoning_effort_levels",
        "default_reasoning_effort",
        "supports_none_reasoning_effort",
        "supports_minimal_reasoning_effort",
        "supports_low_reasoning_effort",
        "supports_xhigh_reasoning_effort",
        "supports_max_reasoning_effort",
    }
)


def _price_field(key: str) -> bool:
    return (
        "cost" in key
        or "price" in key
        or "pricing" in key
        or "billing" in key
        or "multiplier" in key
        or key == "currency"
    )


def _price_evidence(key: str, value: object) -> CatalogPriceEvidence:
    encoded = _encoded_json(value)
    if isinstance(value, _NumberToken):
        if Decimal(value.lexeme) < 0:
            raise CatalogSourceDecodeError("Source price cannot be negative.")
        return CatalogPriceEvidence(
            source_field=key,
            kind="number",
            number=CatalogPriceNumber(lexeme=value.lexeme, token_kind=value.kind),
            encoded_value=encoded,
        )
    if value is None:
        kind = "null"
    elif isinstance(value, dict | list):
        kind = "structured"
    elif isinstance(value, str) and not ("cost" in key or "multiplier" in key):
        kind = "text"
    else:
        raise CatalogSourceDecodeError("Invalid source price declaration.")
    return CatalogPriceEvidence(
        source_field=key, kind=kind, number=None, encoded_value=encoded
    )


def _decode_model(key: str, value: object) -> CatalogSourceModel:
    raw = _object(value)
    provider = _identity(raw.get("litellm_provider"))
    facts = _decode_facts(raw)
    prices = tuple(
        _price_evidence(field, raw[field])
        for field in sorted(raw)
        if _price_field(field)
    )
    extensions = {
        field: raw[field]
        for field in sorted(raw)
        if field != "litellm_provider"
        and field not in _FACT_SOURCE_KEYS
        and not _price_field(field)
    }
    return CatalogSourceModel(
        source_key=_identity(key),
        provider=provider,
        facts=facts,
        reasoning=_interpret_reasoning(provider=provider, facts=facts),
        price_evidence=prices,
        extensions_json=_encoded_json(extensions) if extensions else None,
    )


def decode_catalog_source(raw_bytes: bytes) -> CatalogSourcePayload:
    """Decode bounded catalog data without executing producer code or model rules.

    :param raw_bytes: public catalog JSON bytes
    :returns: canonical typed source evidence with exact scoped lookup
    :raises CatalogSourceDecodeError: invalid or oversized source document
    """
    if not raw_bytes or len(raw_bytes) > CATALOG_SOURCE_MAX_BYTES:
        raise CatalogSourceDecodeError("Source document byte size is out of bounds.")
    try:
        document: object = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_int=_parse_integer,
            parse_float=_parse_decimal,
            parse_constant=_reject_constant,
        )
        raw = _object(document)
        if len(raw) > _MAX_MODELS + len(_NON_MODEL_KEYS):
            raise CatalogSourceDecodeError("Source model count exceeds the limit.")
        # This also bounds opaque extensions before they enter durable evidence.
        _encoded_json(raw).encode("utf-8")
        models = tuple(
            sorted(
                (
                    _decode_model(key, value)
                    for key, value in raw.items()
                    if key not in _NON_MODEL_KEYS
                ),
                key=lambda model: (model.provider, model.source_key),
            )
        )
        if not models or len(models) > _MAX_MODELS:
            raise CatalogSourceDecodeError("Source must contain bounded model records.")
        return CatalogSourcePayload(
            schema_version=CATALOG_SOURCE_SCHEMA_VERSION,
            interpreter_version=CATALOG_SOURCE_INTERPRETER_VERSION,
            models=models,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CatalogSourceDecodeError("Invalid source JSON document.") from exc
