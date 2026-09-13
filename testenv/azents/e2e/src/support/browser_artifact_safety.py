"""Helpers for keeping transient browser callback values out of artifacts."""

import re

_OAUTH_QUERY_PARAMETER = re.compile(
    r"(?P<prefix>(?:[?&]|&amp;|\\u0026)(?:code|state)"
    r"(?:=|%3d|\\u003d)|(?:%3f|%26)(?:code|state)"
    r"(?:%3d|\\u003d))(?P<value>(?:(?!%26(?:code|state)%3d)"
    r"[^&#\"'<> \t\r\n\\])+)",
    re.IGNORECASE,
)
_OAUTH_STRUCTURED_JSON_PARAMETER = re.compile(
    r'(?P<prefix>(?P<escape>\\*)"(?:code|state)(?P=escape)"\s*:\s*(?P=escape)")'
    r'(?P<value>(?:(?!(?P=escape)").)*)'
    r'(?P<suffix>(?P=escape)")',
    re.IGNORECASE,
)
_OAUTH_HTML_JSON_PARAMETER = re.compile(
    r"(?P<prefix>&quot;(?:code|state)&quot;\s*:\s*&quot;)"
    r"(?P<value>(?:(?!&quot;).)*)"
    r"(?P<suffix>&quot;)",
    re.IGNORECASE,
)
_OAUTH_UNICODE_JSON_PARAMETER = re.compile(
    r"(?P<prefix>\\u0022(?:code|state)\\u0022\s*:\s*\\u0022)"
    r"(?P<value>(?:(?!\\u0022).)*)"
    r"(?P<suffix>\\u0022)",
    re.IGNORECASE,
)


def sanitize_browser_artifact(content: str) -> str:
    """Replace OAuth callback code/state values in captured browser text."""
    sanitized = _OAUTH_QUERY_PARAMETER.sub(
        lambda match: f"{match.group('prefix')}<redacted>",
        content,
    )
    sanitized = _OAUTH_STRUCTURED_JSON_PARAMETER.sub(
        lambda match: f"{match.group('prefix')}<redacted>{match.group('suffix')}",
        sanitized,
    )
    sanitized = _OAUTH_HTML_JSON_PARAMETER.sub(
        lambda match: f"{match.group('prefix')}<redacted>{match.group('suffix')}",
        sanitized,
    )
    return _OAUTH_UNICODE_JSON_PARAMETER.sub(
        lambda match: f"{match.group('prefix')}<redacted>{match.group('suffix')}",
        sanitized,
    )
