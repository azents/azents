"""Shared sensitive-text redaction for semantic event projections."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?<![?&])\b"
    r"([a-z0-9_-]*(?:api[_-]?key|authorization|cookie|credential|password|secret|token)"
    r"[a-z0-9_-]*)"
    r"([\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\n,}]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[^\s,;}]+")
_HTTP_URL = re.compile(r"https?://[^\s<>{}\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?"


def sanitize_json_value(value: object, *, key: str | None = None) -> object:
    """Redact sensitive keys and text recursively in one JSON-compatible value."""
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_json_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_sensitive_text(value: str) -> str:
    """Redact access-bearing assignments and HTTP query values."""
    redacted = _SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)
    redacted = _BEARER_VALUE.sub("Bearer [REDACTED]", redacted)
    return "\n".join(redact_url_queries(line) for line in redacted.splitlines())


def redact_url_queries(value: str) -> str:
    """Replace every HTTP query value while preserving safe URL structure."""
    return _HTTP_URL.sub(_redact_url_match, value)


def _redact_url_match(match: re.Match[str]) -> str:
    raw_url = match.group(0)
    url = raw_url.rstrip(_TRAILING_URL_PUNCTUATION)
    suffix = raw_url[len(url) :]
    try:
        parsed = urlsplit(url)
    except ValueError:
        return raw_url
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return raw_url
    netloc = parsed.netloc
    if "@" in netloc:
        _, host = netloc.rsplit("@", 1)
        netloc = f"[REDACTED]@{host}"
    query = parsed.query
    if query:
        query = urlencode(
            [
                (key, "[REDACTED]")
                for key, _ in parse_qsl(query, keep_blank_values=True)
            ],
            safe="[]",
        )
    redacted = urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
    return f"{redacted}{suffix}"
