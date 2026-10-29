"""Payload-free vendor diagnostics for a credential-bearing inference process."""

import logging


class VendorDiagnostics(logging.Filter):
    """Retain diagnostic origin/severity, never vendor payloads or traceback values.

    Prompt/provider bodies and credentials can be embedded in arbitrary vendor
    message strings, exception messages and extra fields. A denylist is therefore
    insufficient at this boundary. Operator events retain logger, source line,
    severity and exception class; the Proxy does not install external exporters.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("azents_llm_proxy"):
            return True
        exception_type = (
            record.exc_info[0].__name__
            if record.exc_info is not None and record.exc_info[0] is not None
            else None
        )
        safe = logging.LogRecord(
            record.name,
            record.levelno,
            record.pathname,
            record.lineno,
            "Vendor inference diagnostic; payload omitted.",
            (),
            None,
            record.funcName,
        )
        record.__dict__.clear()
        record.__dict__.update(safe.__dict__)
        record.__dict__["exception_type"] = exception_type
        return True


def install_vendor_diagnostics() -> None:
    """Composition-root setup before Proxy configuration or accepting requests."""
    boundary = VendorDiagnostics()
    # SDK/Pydantic warnings can include serialized model values too. Route them
    # through the same boundary rather than letting warnings print to stderr.
    logging.getLogger("py.warnings").addFilter(boundary)
    logging.captureWarnings(True)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(boundary)
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.addFilter(boundary)
            for handler in logger.handlers:
                handler.addFilter(boundary)
