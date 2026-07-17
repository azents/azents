import datetime
import enum
import logging
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
    Log record에 context 정보를 추가하는 logger adapter.
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
    Logger에 extra field를 바인딩한다.
    """
    return ContextualLoggerAdapter(logger, extra)


class LoggingFormat(enum.Enum):
    """
    Logging 출력 format.
    """

    CONSOLE = "console"
    JSON = "json"


class RuntimeEnvironment(enum.Enum):
    """
    Application이 실행되는 환경.

    Stage(production, dev 등)와는 다르게, 이 값은 software가 실제로 어디서 실행되는지를
    나타낸다. 예를 들어, production stage를 local에서 테스트할 수도 있다.
    """

    LOCAL = "local"
    DEPLOYED = "deployed"


class HealthCheckFilter(logging.Filter):
    """헬스체크 요청을 access log에서 제외하는 필터.

    Kubernetes, 로드밸런서 등에서 주기적으로 호출되는 헬스체크 요청이
    로그를 과도하게 생성하는 것을 방지한다.

    정확한 경로만 매칭한다 (prefix 매칭 아님).
    uvicorn access log 형식: ``"GET /health/v1/readiness HTTP/1.1" 200``
    경로 앞에 공백이 있으므로 ``" /path "`` 또는 ``" /path?``로 매칭한다.
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
        """헬스체크 요청이면 False를 반환하여 로그를 제외한다."""
        message = record.getMessage()
        for path in self.HEALTHCHECK_PATHS:
            # uvicorn access log: "GET /path HTTP/1.1" 200
            # 경로 뒤에 공백 또는 ?가 오는지 확인하여 정확 매칭
            marker = f" {path} "
            marker_query = f" {path}?"
            if marker in message or marker_query in message:
                return False
        return True


class ConsoleFormatter(DefaultFormatter):
    """
    Log record를 console 친화적인 문자열로 format하는 formatter.

    Extra field는 key=value 쌍의 문자열로 log record에 추가된다.

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
    Logging system을 설정한다.
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
    RuntimeEnvironment에 따라 logging을 설정한다.

    - LOCAL: console format, 기본 INFO level, inhouse DEBUG level
    - DEPLOYED: json format, 기본 WARNING level, inhouse INFO level

    :param runtime_env: 실행 환경
    :param inhouse_name: Inhouse 로거 이름
    :param configure_uvicorn: uvicorn 로깅 설정 여부
    :param sentry_dsn: Sentry DSN (DEPLOYED 환경에서만 초기화됨)
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

        # 헬스체크 요청을 access log에서 제외
        logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())
