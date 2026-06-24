"""Probe-local expect DSL run.

Fixture-first QA probes use the ``expect`` block for deterministic assertions.

Example assertion::

    expect:
      http_status: 200                       # HTTP status code
      response_body:
        contains: ["Connected to"]           # string containment
        not_contains: ["AuthenticationError"]# forbidden text; absence passes
        json_path:
          - path: $.mode                     # jsonpath equals
            equals: byoa
          - path: $.app_id
            matches: "^A[0-9A-Z]+$"          # regex
       bot_reply:
         status: posted                       # posted | not_posted
         latency_s: {max: 30}
         text:
           contains: [...]
           not_contains: ["AuthenticationError", "Traceback"]
           matches_regex: "..."
           min_length: 10

Probe result payloads are compared with ``expect`` values for supported shapes
(``http_status``, ``response_body``, and ``bot_reply``).

``expect`` is strictly validated with a pydantic model. ``extra="forbid"`` turns
unknown fields into :class:`pydantic.ValidationError`, blocking invalid probes.
"""

import logging
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from .types import AssertionResult

logger = logging.getLogger(__name__)


# ----- pydantic schema -----------------------------------------------------


class JsonPathAssertion(BaseModel):
    """``json_path`` item: ``path`` is required; ``equals`` or ``matches`` is allowed."""

    model_config = ConfigDict(extra="forbid")

    path: str
    equals: object | None = None
    matches: str | None = None


class TextAssertion(BaseModel):
    """String assertions for response body and bot_reply.text."""

    model_config = ConfigDict(extra="forbid")

    contains: list[str] | None = None
    not_contains: list[str] | None = None
    matches_regex: str | None = None
    min_length: Annotated[int, Field(ge=0)] | None = None


class ResponseBodyExpect(TextAssertion):
    """``response_body`` assertion: text checks plus optional ``json_path``."""

    json_path: list[JsonPathAssertion] | None = None


class LatencyRange(BaseModel):
    """``bot_reply.latency_s`` range with optional ``max`` and ``min``."""

    model_config = ConfigDict(extra="forbid")

    max: Annotated[float, Field(gt=0)] | None = None
    min: Annotated[float, Field(ge=0)] | None = None


class BotReplyExpect(BaseModel):
    """``bot_reply`` assertion for bot response payloads."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["posted", "not_posted"] | None = None
    latency_s: LatencyRange | None = None
    text: TextAssertion | None = None


class ExpectBlock(BaseModel):
    """Probe-local top-level ``expect`` schema.

    HTTP status codes are constrained to 100-599 as defined by RFC 9110.
    """

    model_config = ConfigDict(extra="forbid")

    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    response_body: ResponseBodyExpect | None = None
    bot_reply: BotReplyExpect | None = None


# ----- public API -----------------------------------------------------------


def parse_expect_block(raw: Mapping[str, object]) -> ExpectBlock:
    """Strictly validate a raw ``expect`` mapping as :class:`ExpectBlock`.

    Pydantic ``extra='forbid'`` rejects unknown fields and raises
    ``pydantic.ValidationError`` for invalid input.

    :param raw: raw ``expect`` mapping from a probe.
    :returns: validated :class:`ExpectBlock`.
    :raises pydantic.ValidationError: when fields are unknown or invalid.
    """
    return ExpectBlock.model_validate(raw)


def run_expect_block(
    expect: ExpectBlock,
    tc_result: Mapping[str, object],
) -> list[AssertionResult]:
    """Run an ``expect`` block and return assertion results.

    The caller must pass a validated :class:`ExpectBlock`, usually produced by
    :func:`parse_expect_block`.

    :param expect: validated :class:`ExpectBlock`.
    :param tc_result: raw result payload from a probe.
    :returns: zero or more :class:`AssertionResult` objects.
    """
    results: list[AssertionResult] = []

    # http_status
    if expect.http_status is not None:
        expected = expect.http_status
        actual = tc_result.get("http_status")
        results.append(
            AssertionResult(
                assertion_type="http_status",
                passed=actual == expected,
                expected=expected,
                actual=actual,
                detail=f"http_status expected={expected!r} actual={actual!r}",
            )
        )

    # response_body
    if expect.response_body is not None:
        actual_body = tc_result.get("response_body")
        results.extend(_assert_text_like("response_body", expect.response_body, actual_body))
        if expect.response_body.json_path is not None:
            results.extend(_assert_json_path(expect.response_body.json_path, actual_body))

    # bot_reply
    if expect.bot_reply is not None:
        actual_reply = tc_result.get("bot_reply")
        results.extend(_assert_bot_reply(expect.bot_reply, actual_reply))

    return results


# ----- text-like (contains / not_contains / matches_regex / min_length) ----


def _assert_text_like(
    prefix: str,
    expect: TextAssertion,
    actual: object,
) -> list[AssertionResult]:
    """Run ``contains``, ``not_contains``, ``matches_regex``, and ``min_length``.

    Non-string ``actual`` values are coerced with ``str(actual)`` for JSON-like
    payloads. ``None`` is treated as an empty string.
    """
    results: list[AssertionResult] = []
    actual_str = actual if isinstance(actual, str) else ("" if actual is None else str(actual))

    if expect.contains is not None:
        for needle in expect.contains:
            passed = needle in actual_str
            results.append(
                AssertionResult(
                    assertion_type=f"{prefix}.contains",
                    passed=passed,
                    expected=needle,
                    actual=_truncate(actual_str),
                    detail=f"{prefix} should contain {needle!r}",
                )
            )

    if expect.not_contains is not None:
        for needle in expect.not_contains:
            passed = needle not in actual_str
            results.append(
                AssertionResult(
                    assertion_type=f"{prefix}.not_contains",
                    passed=passed,
                    expected=f"not contain {needle!r}",
                    actual=_truncate(actual_str),
                    detail=f"{prefix} must NOT contain {needle!r}",
                )
            )

    if expect.matches_regex is not None:
        regex = expect.matches_regex
        try:
            passed = re.search(regex, actual_str) is not None
        except re.error as exc:
            passed = False
            logger.warning("invalid regex %r: %s", regex, exc)
        results.append(
            AssertionResult(
                assertion_type=f"{prefix}.matches_regex",
                passed=passed,
                expected=regex,
                actual=_truncate(actual_str),
                detail=f"{prefix} should match regex {regex!r}",
            )
        )

    if expect.min_length is not None:
        min_length = expect.min_length
        passed = len(actual_str) >= min_length
        results.append(
            AssertionResult(
                assertion_type=f"{prefix}.min_length",
                passed=passed,
                expected=min_length,
                actual=len(actual_str),
                detail=f"{prefix} length >= {min_length}",
            )
        )

    return results


# ----- json_path assertion --------------------------------------------------


def _assert_json_path(
    json_path_spec: list[JsonPathAssertion],
    actual: object,
) -> list[AssertionResult]:
    """Run ``json_path: [{path, equals | matches}]`` assertions.

    This intentionally supports only a small dotted-path subset such as
    ``$.a.b.c`` and array indexes such as ``$.a.0.b``. More complex JSONPath
    queries are out of scope for these deterministic assertions.
    """
    results: list[AssertionResult] = []

    for item in json_path_spec:
        path_expr = item.path
        value = _resolve_json_path(actual, path_expr)

        # Allow None as a valid expected value when the field is explicitly set.
        if "equals" in item.model_fields_set:
            expected = item.equals
            passed = value == expected
            results.append(
                AssertionResult(
                    assertion_type="response_body.json_path.equals",
                    passed=passed,
                    expected={"path": path_expr, "equals": expected},
                    actual=value,
                    detail=f"{path_expr} should equal {expected!r}",
                )
            )
        if item.matches is not None:
            pattern = item.matches
            value_str = "" if value is None else str(value)
            try:
                passed = re.search(pattern, value_str) is not None
            except re.error:
                passed = False
            results.append(
                AssertionResult(
                    assertion_type="response_body.json_path.matches",
                    passed=passed,
                    expected={"path": path_expr, "matches": pattern},
                    actual=_truncate(value_str),
                    detail=f"{path_expr} should match {pattern!r}",
                )
            )

    return results


def _resolve_json_path(root: object, expr: str) -> object:
    """Resolve a small dotted-path expression such as ``$.a.b.0.c``."""
    if not expr.startswith("$"):
        return None
    expr = expr[1:]
    if expr.startswith("."):
        expr = expr[1:]
    if not expr:
        return root
    cursor: Any = root
    for raw_part in expr.split("."):
        if raw_part == "":
            continue
        if cursor is None:
            return None
        if isinstance(cursor, list) and raw_part.isdigit():
            idx = int(raw_part)
            if 0 <= idx < len(cursor):
                cursor = cursor[idx]
            else:
                return None
        elif isinstance(cursor, dict):
            cursor = cast(dict[str, object], cursor).get(raw_part)
        else:
            return None
    return cursor


# ----- bot_reply -----------------------------------------------------------


def _assert_bot_reply(
    expect: BotReplyExpect,
    actual: object,
) -> list[AssertionResult]:
    """``bot_reply`` assertion.

    Actual shape::

        {
          "status": "posted",
          "latency_s": 2.3,
          "text": "Hello world",
          "channel_id": "C...",
          "ts": "1775961394.123456"
        }
    """
    results: list[AssertionResult] = []
    actual_dict = cast(dict[str, object], actual) if isinstance(actual, dict) else {}

    # Status defaults to "posted" when not specified.
    status_expect = expect.status if expect.status is not None else "posted"
    actual_status = actual_dict.get("status")
    results.append(
        AssertionResult(
            assertion_type="bot_reply.status",
            passed=actual_status == status_expect,
            expected=status_expect,
            actual=actual_status,
            detail=f"bot_reply.status expected={status_expect!r} actual={actual_status!r}",
        )
    )

    # latency_s
    if expect.latency_s is not None:
        actual_lat = actual_dict.get("latency_s")
        if expect.latency_s.max is not None:
            max_v = expect.latency_s.max
            passed = isinstance(actual_lat, (int, float)) and actual_lat <= max_v
            results.append(
                AssertionResult(
                    assertion_type="bot_reply.latency_s.max",
                    passed=passed,
                    expected=max_v,
                    actual=actual_lat,
                    detail=f"bot_reply latency <= {max_v}s",
                )
            )
        if expect.latency_s.min is not None:
            min_v = expect.latency_s.min
            passed = isinstance(actual_lat, (int, float)) and actual_lat >= min_v
            results.append(
                AssertionResult(
                    assertion_type="bot_reply.latency_s.min",
                    passed=passed,
                    expected=min_v,
                    actual=actual_lat,
                    detail=f"bot_reply latency >= {min_v}s",
                )
            )

    # text
    if expect.text is not None:
        actual_text = actual_dict.get("text", "")
        results.extend(_assert_text_like("bot_reply.text", expect.text, actual_text))

    return results


# ----- utils ---------------------------------------------------------------


def _truncate(text: str, limit: int = 500) -> str:
    """Truncate a long string for assertion output."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... (+{len(text) - limit} chars)"


def all_passed(results: list[AssertionResult]) -> bool:
    """Return whether every assertion passed."""
    return all(r.passed for r in results)


def summarize_failures(results: list[AssertionResult]) -> str:
    """Return a summary of failed assertions."""
    fails = [r for r in results if not r.passed]
    if not fails:
        return ""
    lines = [f"- [{r.assertion_type}] {r.detail} (actual={r.actual!r})" for r in fails]
    return "\n".join(lines)
