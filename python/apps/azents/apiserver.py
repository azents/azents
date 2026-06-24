"""Public API server entry point.

Run with uvicorn:
    uvicorn apiserver:app --reload --port 8010
"""

from azcommon.logging import configure_logging_for_runtime

from azents.app import create_public_api_app
from azents.core.config import Config

config = Config.from_env()

configure_logging_for_runtime(
    runtime_env=config.runtime_env,
    inhouse_name="azents",
    configure_uvicorn=True,
    sentry_dsn=config.sentry_dsn,
)

app = create_public_api_app(config)
