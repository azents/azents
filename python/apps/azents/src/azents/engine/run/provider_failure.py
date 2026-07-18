"""Provider-neutral model failure classification and safe presentation."""

import enum
import hashlib
import json
import re

from azents.engine.run.errors import ModelCallError, ModelStreamCallKind

_PROVIDER_MESSAGE_MAX_INPUT_CHARS = 8 * 1024
_PROVIDER_MESSAGE_MAX_CHARS = 1000
_PROVIDER_IDENTIFIER_MAX_CHARS = 96
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"cookie|set-cookie|secret|password)\s*[:=]\s*([^\s,;]+)"
)
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_PATTERN = re.compile(r"\b(?:sk|sess|key)-[A-Za-z0-9_-]{8,}\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@", re.I)
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_URL_PATTERN = re.compile(r"https?://\S+", re.I)
_LONG_IDENTIFIER_PATTERN = re.compile(r"\b[a-f0-9]{16,}\b", re.I)
_NUMBER_PATTERN = re.compile(r"\b\d+\b")
_SDK_SERIALIZED_ERROR_PATTERN = re.compile(r"(?i)\berror code:\s*\d+\s*-\s*[\[{]")


class ModelProviderFailureCategory(enum.StrEnum):
    """Closed provider-neutral semantic failure taxonomy."""

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    QUOTA_OR_BILLING = "quota_or_billing"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONTEXT_LIMIT = "context_limit"
    CONTENT_POLICY = "content_policy"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


class ModelProviderFailureRetryability(enum.StrEnum):
    """Diagnostic retryability retained independently from retry budget policy."""

    TRANSIENT = "transient"
    USER_ACTION_REQUIRED = "user_action_required"
    NON_RETRYABLE = "non_retryable"
    UNKNOWN = "unknown"


class ModelProviderFailure(ModelCallError):
    """One safe provider-attributed failure crossing the Engine boundary."""

    operation: ModelStreamCallKind
    category: ModelProviderFailureCategory
    retryability: ModelProviderFailureRetryability
    provider_message: str | None
    status_code: int | None
    provider_code: str | None
    provider_error_type: str | None
    retry_hint_seconds: float | None
    provider: str
    integration: str | None
    model: str
    failure_code: str
    fingerprint: str

    def __init__(
        self,
        *,
        operation: ModelStreamCallKind,
        category: ModelProviderFailureCategory,
        retryability: ModelProviderFailureRetryability,
        provider_message: str | None,
        status_code: int | None,
        provider_code: str | None,
        provider_error_type: str | None,
        retry_hint_seconds: float | None,
        provider: str,
        integration: str | None,
        model: str,
    ) -> None:
        """Store only bounded provider-neutral fields and safe display text."""
        safe_message = sanitize_provider_message(provider_message)
        safe_provider = sanitize_provider_identifier(provider) or "unknown"
        safe_integration = sanitize_provider_identifier(integration)
        safe_model = sanitize_provider_identifier(model) or "unknown"
        safe_code = sanitize_provider_identifier(provider_code)
        safe_error_type = sanitize_provider_identifier(provider_error_type)
        safe_status = (
            status_code
            if isinstance(status_code, int) and 100 <= status_code <= 599
            else None
        )
        safe_retry_hint = (
            float(retry_hint_seconds)
            if isinstance(retry_hint_seconds, int | float)
            and not isinstance(retry_hint_seconds, bool)
            and 0 <= retry_hint_seconds <= 86_400
            else None
        )
        display_message = safe_message or (
            "The model provider could not process the request."
        )
        super().__init__(f"Model provider error: {display_message}")
        self.operation = operation
        self.category = category
        self.retryability = retryability
        self.provider_message = safe_message
        self.status_code = safe_status
        self.provider_code = safe_code
        self.provider_error_type = safe_error_type
        self.retry_hint_seconds = safe_retry_hint
        self.provider = safe_provider
        self.integration = safe_integration
        self.model = safe_model
        self.failure_code = f"model_provider_{category.value}"
        self.fingerprint = model_provider_failure_fingerprint(self)


def model_provider_failure(
    *,
    operation: ModelStreamCallKind,
    provider: str,
    model: str,
    integration: str | None,
    provider_message: object,
    status_code: int | None,
    provider_code: object,
    provider_error_type: object,
    retry_hint_seconds: float | None = None,
    category: ModelProviderFailureCategory | None = None,
) -> ModelProviderFailure:
    """Build one classified provider failure from typed adapter fields."""
    safe_code = sanitize_provider_identifier(provider_code)
    safe_error_type = sanitize_provider_identifier(provider_error_type)
    resolved_category = category or classify_model_provider_failure(
        status_code=status_code,
        provider_code=safe_code,
        provider_error_type=safe_error_type,
    )
    return ModelProviderFailure(
        operation=operation,
        category=resolved_category,
        retryability=provider_failure_retryability(resolved_category),
        provider_message=(
            provider_message if isinstance(provider_message, str) else None
        ),
        status_code=status_code,
        provider_code=safe_code,
        provider_error_type=safe_error_type,
        retry_hint_seconds=retry_hint_seconds,
        provider=provider,
        integration=integration,
        model=model,
    )


def sanitize_provider_message(value: object) -> str | None:
    """Return bounded provider-authored scalar text with secrets redacted."""
    if not isinstance(value, str) or len(value) > _PROVIDER_MESSAGE_MAX_INPUT_CHARS:
        return None
    message = _CONTROL_PATTERN.sub(" ", value).strip()
    if not message:
        return None
    lowered = message.lower()
    if (lowered.startswith("<html") or lowered.startswith("<!doctype")) and len(
        message
    ) > 128:
        return None
    if message[:1] in {"{", "["} and len(message) > 256:
        return None
    message = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", message)
    message = _AUTH_SCHEME_PATTERN.sub(r"\1 [REDACTED]", message)
    message = _SECRET_VALUE_PATTERN.sub(r"\1=[REDACTED]", message)
    message = _TOKEN_PATTERN.sub("[REDACTED]", message)
    message = _WHITESPACE_PATTERN.sub(" ", message).strip()
    if not message:
        return None
    return message[:_PROVIDER_MESSAGE_MAX_CHARS]


def extract_provider_message_text(value: object) -> str | None:
    """Extract scalar provider text without retaining SDK error serialization."""
    if not isinstance(value, str):
        return None
    message = value.strip()
    if not message or _SDK_SERIALIZED_ERROR_PATTERN.search(message):
        return None
    if message[:1] not in {"{", "["}:
        return message
    try:
        decoded = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    nested = decoded.get("error")
    error = nested if isinstance(nested, dict) else decoded
    for key in ("message", "detail"):
        candidate = error.get(key)
        if isinstance(candidate, str):
            return candidate
    return None


def sanitize_provider_identifier(value: object) -> str | None:
    """Return one bounded code-like identifier or no value."""
    if not isinstance(value, str):
        return None
    identifier = value.strip()[:_PROVIDER_IDENTIFIER_MAX_CHARS]
    if not identifier or not all(
        char.isalnum() or char in {"_", "-", ".", "/", ":"} for char in identifier
    ):
        return None
    return identifier


def classify_model_provider_failure(
    *,
    status_code: int | None,
    provider_code: str | None,
    provider_error_type: str | None,
) -> ModelProviderFailureCategory:
    """Classify status and provider identifiers into the closed taxonomy."""
    identifiers = " ".join(
        _normalize_failure_identifier(value)
        for value in (provider_code, provider_error_type)
        if value
    )
    if status_code == 401 or _contains_any(
        identifiers,
        "authentication",
        "unauthorized",
        "invalid_api_key",
        "invalid_token",
    ):
        return ModelProviderFailureCategory.AUTHENTICATION
    if status_code == 403 or _contains_any(
        identifiers,
        "permission",
        "forbidden",
        "access_denied",
    ):
        return ModelProviderFailureCategory.PERMISSION
    if status_code == 402 or _contains_any(
        identifiers,
        "insufficient_quota",
        "quota",
        "billing",
        "credit_balance",
    ):
        return ModelProviderFailureCategory.QUOTA_OR_BILLING
    if status_code == 429 or _contains_any(
        identifiers,
        "rate_limit",
        "too_many_requests",
    ):
        return ModelProviderFailureCategory.RATE_LIMIT
    if _contains_any(
        identifiers,
        "context_length",
        "context_window",
        "max_context",
        "input_too_long",
    ):
        return ModelProviderFailureCategory.CONTEXT_LIMIT
    if _contains_any(
        identifiers,
        "content_filter",
        "content_policy",
        "safety",
        "bio_policy",
        "cyber_policy",
        "policy_violation",
    ):
        return ModelProviderFailureCategory.CONTENT_POLICY
    if status_code == 404 or _contains_any(
        identifiers,
        "model_not_found",
        "model_unavailable",
        "unsupported_model",
    ):
        return ModelProviderFailureCategory.MODEL_UNAVAILABLE
    if _contains_any(
        identifiers,
        "connection",
        "transport",
        "websocket",
        "network",
        "timeout",
    ):
        return ModelProviderFailureCategory.TRANSPORT
    if (status_code is not None and status_code >= 500) or _contains_any(
        identifiers,
        "server_error",
        "service_unavailable",
        "provider_unavailable",
        "overloaded",
    ):
        return ModelProviderFailureCategory.PROVIDER_UNAVAILABLE
    if (status_code is not None and 400 <= status_code <= 499) or _contains_any(
        identifiers,
        "invalid_request",
        "bad_request",
        "invalid_prompt",
        "invalid_image",
        "unsupported",
        "malformed",
        "max_output_tokens",
    ):
        return ModelProviderFailureCategory.INVALID_REQUEST
    return ModelProviderFailureCategory.UNKNOWN


def provider_failure_retryability(
    category: ModelProviderFailureCategory,
) -> ModelProviderFailureRetryability:
    """Return diagnostic retryability without changing the full-budget policy."""
    if category in {
        ModelProviderFailureCategory.RATE_LIMIT,
        ModelProviderFailureCategory.PROVIDER_UNAVAILABLE,
        ModelProviderFailureCategory.TRANSPORT,
    }:
        return ModelProviderFailureRetryability.TRANSIENT
    if category in {
        ModelProviderFailureCategory.AUTHENTICATION,
        ModelProviderFailureCategory.PERMISSION,
        ModelProviderFailureCategory.QUOTA_OR_BILLING,
    }:
        return ModelProviderFailureRetryability.USER_ACTION_REQUIRED
    if category in {
        ModelProviderFailureCategory.INVALID_REQUEST,
        ModelProviderFailureCategory.MODEL_UNAVAILABLE,
        ModelProviderFailureCategory.CONTEXT_LIMIT,
        ModelProviderFailureCategory.CONTENT_POLICY,
    }:
        return ModelProviderFailureRetryability.NON_RETRYABLE
    return ModelProviderFailureRetryability.UNKNOWN


def model_provider_failure_fingerprint(failure: ModelProviderFailure) -> str:
    """Return a safe stable hash for structured logging and grouping."""
    message_shape = _provider_message_shape(failure.provider_message)
    raw = "|".join(
        [
            failure.provider,
            failure.operation,
            str(failure.status_code or ""),
            failure.provider_code or "",
            failure.provider_error_type or "",
            message_shape,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _provider_message_shape(message: str | None) -> str:
    if message is None:
        return ""
    shaped = _URL_PATTERN.sub("<url>", message.lower())
    shaped = _LONG_IDENTIFIER_PATTERN.sub("<id>", shaped)
    shaped = _NUMBER_PATTERN.sub("#", shaped)
    return _WHITESPACE_PATTERN.sub(" ", shaped).strip()[:256]


def _normalize_failure_identifier(value: str) -> str:
    """Normalize provider identifiers and SDK class names for classification."""
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return snake_case.lower().replace("-", "_").replace(".", "_")


def _contains_any(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
