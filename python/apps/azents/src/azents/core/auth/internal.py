"""Internal endpoint HMAC signature verification utilities.

The ``/internal/*`` endpoint group authenticates cluster-internal trusted callers,
such as Pod preStop hooks, with HMAC-SHA256 and a timestamp replay window. This
is separate from public API authentication and is extracted as a reusable utility
so multiple endpoints can share the same verification rules.

Payload format differs by endpoint. For example, ``/terminate`` uses
``{agent_id}:{timestamp}:{nonce}``, but :func:`verify_signature` below validates
only payload bytes, signature, and timestamp, so callers only build the payload.
"""

import datetime
import hashlib
import hmac
import logging
from typing import Any

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Internal HMAC signature header: fixed name shared with callers such as preStop hooks.
SIGNATURE_HEADER = "X-Snapshot-Signature"
# Default replay window in seconds. Older or future timestamps are rejected.
DEFAULT_REPLAY_WINDOW_SECS = 60


def compute_signature(secret: bytes, payload: bytes) -> str:
    """Calculate HMAC-SHA256 hex digest for ``payload``.

    :param secret: Shared secret (bytes)
    :param payload: Payload bytes to sign
    :return: Hex digest, 64 characters
    """
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_signature(
    *,
    secret: bytes,
    payload: bytes,
    signature: str,
    timestamp: int,
    window_secs: int = DEFAULT_REPLAY_WINDOW_SECS,
    log_context: dict[str, Any] | None = None,
) -> None:
    """Validate HMAC-SHA256 signature and timestamp replay window.

    Raises 401 ``invalid_signature`` when the signature differs. Raises 401
    ``stale_timestamp`` when timestamp is outside the window, either past or
    future. Used by endpoints, such as Pod preStop, where callers must receive
    a recoverable 401 response.

    :param secret: HMAC shared secret
    :param payload: Bytes to sign; payload format differs per endpoint
    :param signature: Signature sent by caller as hex digest
    :param timestamp: Unix seconds sent by caller for replay window validation
    :param window_secs: Allowed replay window in seconds. Default 60 seconds
    :param log_context: Additional context for warning logs, such as
        ``{"agent_id": "..."}``. Used for structured logging.
    :raises HTTPException: 401 (``invalid_signature`` / ``stale_timestamp``)
    """
    extra = dict(log_context or {})

    expected = compute_signature(secret, payload)
    if not hmac.compare_digest(expected, signature):
        logger.warning("internal_invalid_signature", extra=extra)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_signature",
        )

    now_ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    drift = abs(now_ts - timestamp)
    if drift > window_secs:
        logger.warning(
            "internal_stale_timestamp",
            extra={**extra, "drift_secs": drift, "window_secs": window_secs},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="stale_timestamp",
        )
