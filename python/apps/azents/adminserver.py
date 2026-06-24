"""Admin API server entry point.

Run with uvicorn:
    uvicorn adminserver:app --reload --port 8011
"""

from azcommon.logging import configure_logging_for_runtime

from azents.app import create_admin_api_app
from azents.core.config import Config

config = Config.from_env()

configure_logging_for_runtime(
    runtime_env=config.runtime_env,
    inhouse_name="azents",
    configure_uvicorn=True,
    sentry_dsn=config.sentry_dsn,
)
app = create_admin_api_app(config)
