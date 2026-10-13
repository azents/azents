"""Bounded known-pattern Google MCP screening, not a prevention guarantee."""

import base64
import binascii
import dataclasses
import re
import unicodedata
from urllib.parse import unquote


class GoogleContentBlocked(ValueError):
    """Safe content category; never retain the blocked payload in an exception."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("Google content could not be safely inspected: " + reason)


@dataclasses.dataclass(frozen=True)
class GoogleScreeningLimits:
    """Inspection resource budgets; exceeding any budget blocks the whole item."""

    max_depth: int
    max_nodes: int
    max_string_chars: int
    max_total_chars: int


DEFAULT_GOOGLE_SCREENING_LIMITS = GoogleScreeningLimits(24, 10000, 131072, 262144)
_PATTERNS = (
    (
        "instruction_override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\s+(?:(?:all|any|the|your)\s+)?"
            r"(?:previous|prior|above|system|developer)\s+(?:instructions?|prompts?|rules?)",
            re.I,
        ),
    ),
    (
        "role_spoofing",
        re.compile(
            r"(?:<\|(?:im_start|start_header_id|system|developer)\|>|"
            r"\[\s*(?:system|developer)\s*\]\s*:|"
            r"(?:^|\n)\s*(?:system|developer)\s*:\s*(?:you must|ignore|override))",
            re.I,
        ),
    ),
    (
        "credential_exfiltration",
        re.compile(
            r"\b(?:send|upload|post|transmit|reveal|print|exfiltrate)\s+"
            r"(?:(?:all|the|your|any|stored)\s+)*"
            r"(?:api[\s_-]*keys?|access[\s_-]*tokens?|refresh[\s_-]*tokens?|"
            r"credentials?|passwords?|system[\s_-]*prompts?|developer[\s_-]*prompts?)\b",
            re.I,
        ),
    ),
    (
        "tool_commandeering",
        re.compile(
            r"\b(?:instead|before answering|regardless of (?:the )?user)"
            r"[^\n]{0,80}\b(?:call|invoke|execute)\s+(?:the\s+)?"
            r"(?:exec_command|shell|terminal|write_stdin|delete_memory)\b",
            re.I,
        ),
    ),
)
_BASE64 = re.compile(r"\bbase64\s*:\s*([A-Za-z0-9+/]{8,}={0,2})", re.I)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        char
        for char in normalized
        if unicodedata.category(char) not in {"Cf", "Cc"} or char in "\n\t\r"
    )


def inspect_google_content(
    value: object,
    *,
    limits: GoogleScreeningLimits = DEFAULT_GOOGLE_SCREENING_LIMITS,
) -> None:
    """Inspect complete JSON-compatible content; do not log or rewrite its text."""
    strings: list[str] = []
    nodes = 0
    chars = 0

    def visit(item: object, depth: int) -> None:
        nonlocal nodes, chars
        nodes += 1
        if depth > limits.max_depth or nodes > limits.max_nodes:
            raise GoogleContentBlocked("structure_budget")
        if isinstance(item, str):
            chars += len(item)
            if len(item) > limits.max_string_chars or chars > limits.max_total_chars:
                raise GoogleContentBlocked("content_budget")
            strings.append(item)
        elif item is None or isinstance(item, bool | int | float):
            return
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise GoogleContentBlocked("unsupported_structure")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, list | tuple):
            for child in item:
                visit(child, depth + 1)
        else:
            raise GoogleContentBlocked("unsupported_structure")

    visit(value, 0)
    # A complete joined view also detects tested directives split across fields.
    views = [_normalize("\n".join(strings))]
    decoded_chars = 0
    for text in strings:
        try:
            decoded = unquote(text, errors="strict")
        except UnicodeDecodeError:
            raise GoogleContentBlocked("unsupported_encoding") from None
        if decoded != text:
            decoded_chars += len(decoded)
            views.append(_normalize(decoded))
        for match in _BASE64.finditer(text):
            try:
                decoded = base64.b64decode(match[1], validate=True).decode("utf-8")
            except binascii.Error, UnicodeDecodeError:
                raise GoogleContentBlocked("unsupported_encoding") from None
            decoded_chars += len(decoded)
            views.append(_normalize(decoded))
        if chars + decoded_chars > limits.max_total_chars:
            raise GoogleContentBlocked("content_budget")
    for view in views:
        for reason, pattern in _PATTERNS:
            if pattern.search(view):
                raise GoogleContentBlocked(reason)
