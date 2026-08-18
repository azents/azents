import datetime
import enum
import logging
import re
import sys
from typing import TYPE_CHECKING, Any, MutableMapping, TypeVar, assert_never

import click
import sentry_sdk
from pythonjsonlogger.core import RESERVED_ATTRS
from pythonjsonlogger.json import JsonFormatter
from typing_extensions import override
from uvicorn.logging import DefaultFormatter

if TYPE_CHECKING:
    from sentry_sdk._types import Event, Hint

STANDARD_LOG_RECORD_KEYS = frozenset(
    [
        "name",
        "levelname",
        "pathname",
        "lineno",
        "funcName",
        "created",
        "asctime",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "process",
        "message",
        "args",
        "exc_info",
        "exc_text",
        "stack_info",
        "levelno",
        "msg",
        "filename",
        "module",
        "processName",
        "color_message",
        "taskName",
    ]
)


LoggerType = logging.Logger | logging.LoggerAdapter[Any]
L = TypeVar("L", bound=LoggerType)


class ContextualLoggerAdapter(logging.LoggerAdapter[L]):
    """
    Logger adapter that adds context to log records.
    """

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        if self.extra is not None:
            extra = dict(self.extra)
            extra.update(kwargs.get("extra", {}))
            kwargs["extra"] = extra
        return msg, kwargs


def bind_extra(logger: L, extra: MutableMapping[str, Any]) -> logging.LoggerAdapter[L]:
    """
    Bind extra fields to a logger.
    """
    return ContextualLoggerAdapter(logger, extra)


class LoggingFormat(enum.Enum):
    """
    Logging output format.
    """

    CONSOLE = "console"
    JSON = "json"


class RuntimeEnvironment(enum.Enum):
    """
    Environment in which the application runs.

    Unlike a stage such as production or development, this value describes
    where the software actually runs. For example, a production stage may be
    tested locally.
    """

    LOCAL = "local"
    DEPLOYED = "deployed"


class HealthCheckFilter(logging.Filter):
    """Filter that excludes health check requests from access logs.

    Prevents health checks periodically sent by Kubernetes, load balancers,
    and similar systems from generating excessive logs.

    Matches exact paths rather than prefixes.
    Uvicorn access log format: ``"GET /health/v1/readiness HTTP/1.1" 200``
    Because the path is preceded by a space, match ``" /path "`` or ``" /path?``.
    """

    HEALTHCHECK_PATHS = frozenset(
        {
            "/health",
            "/health/v1/readiness",
            "/health/v1/liveness",
            "/healthz",
            "/readyz",
        }
    )

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False for a health check request to exclude its log entry."""
        message = record.getMessage()
        for path in self.HEALTHCHECK_PATHS:
            # uvicorn access log: "GET /path HTTP/1.1" 200
            # Require a space or question mark after the path for an exact match
            marker = f" {path} "
            marker_query = f" {path}?"
            if marker in message or marker_query in message:
                return False
        return True


_SENSITIVE_QUERY_PARAMETER_PATTERN = re.compile(
    r"([?&]ticket=)[^&\s\"']+",
    flags=re.IGNORECASE,
)


class SensitiveQueryParameterFilter(logging.Filter):
    """Redact sensitive query parameter values before log handlers run."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact WebSocket ticket values in formatted and parameterized logs."""
        if isinstance(record.msg, str):
            record.msg = _redact_sensitive_query_parameters(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_sensitive_query_parameters(value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: (
                    _redact_sensitive_query_parameters(value)
                    if isinstance(value, str)
                    else value
                )
                for key, value in record.args.items()
            }
        return True


def _redact_sensitive_query_parameters(value: str) -> str:
    """Replace sensitive query parameter values with a fixed placeholder."""
    return _SENSITIVE_QUERY_PARAMETER_PATTERN.sub(r"\1<redacted>", value)


class ConsoleFormatter(DefaultFormatter):
    """
    Formatter that renders log records as console-friendly strings.

    Extra fields are appended to the log record as key=value pairs.

    .. code-block:: python

        import logging

        logger = logging.getLogger(__name__)
        logger.info("Hello, world!", extra={"foo": "bar"})

        # Output:
        # 2025-01-01 12:00:00 INFO:     Hello, world! foo=bar (my_logger)

    """

    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelprefix)s %(message)s %(extra)s (%(name)s)",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        extra: dict[str, Any] = {}

        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_RECORD_KEYS:
                extra[key] = value
        extra_formatted = ", ".join(f"{k}={v!r}" for k, v in extra.items())
        if self.use_colors:
            extra_formatted = click.style(extra_formatted, fg="yellow")
        record.__dict__.update(extra=extra_formatted)

        if self.use_colors:
            record.name = click.style(record.name, fg="cyan")
        return super().format(record)


class StandardJsonFormatter(JsonFormatter):
    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        if datefmt is None:
            return (
                datetime.datetime.fromtimestamp(record.created).astimezone().isoformat()
            )
        return super().formatTime(record, datefmt)


def configure_logging(
    *,
    format: LoggingFormat,
    default_level: int | str,
    levels: dict[str, int | str],
) -> None:
    """
    Configure the logging system.
    """
    root_logger = logging.getLogger()

    if format == LoggingFormat.CONSOLE:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ConsoleFormatter())

        logging.basicConfig(
            handlers=[handler],
        )

        root_logger.setLevel(default_level)
        for name, level in levels.items():
            name_logger = logging.getLogger(name)
            name_logger.setLevel(level)
    elif format == LoggingFormat.JSON:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            StandardJsonFormatter(
                [
                    "levelname",
                    "name",
                    "asctime",
                    "message",
                    "exc_info",
                    "filename",
                    "funcName",
                    "lineno",
                    "process",
                    "processName",
                    "thread",
                    "threadName",
                ],
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                },
                # https://nhairs.github.io/python-json-logger/latest/quickstart/#excluding-fields
                reserved_attrs=RESERVED_ATTRS + ["color_message"],
            )
        )

        logging.basicConfig(
            handlers=[handler],
        )

        root_logger.setLevel(default_level)
        for name, level in levels.items():
            name_logger = logging.getLogger(name)
            name_logger.setLevel(level)
    else:
        assert_never(format)


def apply_structured_sentry_fingerprint(
    event: "Event",
    hint: "Hint",
) -> "Event":
    """Map approved structured log fingerprints into Sentry grouping."""
    del hint
    extra = event.get("extra")
    if not isinstance(extra, MutableMapping):
        return event
    provider_fingerprint = extra.get("provider_failure_fingerprint")
    if not isinstance(provider_fingerprint, str) or not provider_fingerprint:
        return event
    fingerprint = ["model-provider-failure", provider_fingerprint]
    release = event.get("release")
    if isinstance(release, str) and release:
        fingerprint.append(release)
    event["fingerprint"] = fingerprint
    return event


def configure_logging_for_runtime(
    *,
    runtime_env: RuntimeEnvironment,
    inhouse_name: str,
    configure_uvicorn: bool = False,
    sentry_dsn: str | None = None,
) -> None:
    """
    Configure logging for the RuntimeEnvironment.

    - LOCAL: console format, default INFO level, in-house DEBUG level
    - DEPLOYED: JSON format, default WARNING level, in-house INFO level

    :param runtime_env: Runtime environment.
    :param inhouse_name: In-house logger name.
    :param configure_uvicorn: Whether to configure Uvicorn logging.
    :param sentry_dsn: Sentry DSN, initialized only in DEPLOYED environments.
    """
    # Initialize Sentry only in deployed environment
    if runtime_env == RuntimeEnvironment.DEPLOYED and sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            before_send=apply_structured_sentry_fingerprint,
        )

    if runtime_env == RuntimeEnvironment.LOCAL:
        configure_logging(
            format=LoggingFormat.CONSOLE,
            default_level=logging.INFO,
            levels={
                inhouse_name: logging.DEBUG,
                "__main__": logging.DEBUG,
                **(
                    {
                        "uvicorn": logging.INFO,
                        "uvicorn.access": logging.INFO,
                    }
                    if configure_uvicorn
                    else {}
                ),
            },
        )
    elif runtime_env == RuntimeEnvironment.DEPLOYED:
        configure_logging(
            format=LoggingFormat.JSON,
            default_level=logging.WARNING,
            levels={
                inhouse_name: logging.INFO,
                "__main__": logging.INFO,
                **(
                    {
                        "uvicorn": logging.INFO,
                        "uvicorn.access": logging.INFO,
                    }
                    if configure_uvicorn
                    else {}
                ),
            },
        )
    else:
        assert_never(runtime_env)
    if configure_uvicorn:
        # Clear custom rich handlers of uvicorn and uvicorn.access
        logging.getLogger("uvicorn.error").handlers.clear()
        logging.getLogger("uvicorn.access").handlers.clear()
        logging.getLogger("uvicorn").handlers.clear()

        # Option A: disable propagation of all uvicorn logs
        logging.getLogger("uvicorn").propagate = True
        logging.getLogger("uvicorn.access").propagate = True
        logging.getLogger("uvicorn.error").propagate = True

        # Exclude health check requests from access logs
        logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

        sensitive_query_filter = SensitiveQueryParameterFilter()
        logging.getLogger("uvicorn.access").addFilter(sensitive_query_filter)
        logging.getLogger("uvicorn.error").addFilter(sensitive_query_filter)
