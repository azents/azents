"""OpenAPI client factories.

`TestenvConfig` is a required positional dependency. There is no implicit
default fallback; callers that want environment values should use
`testenv.runtime_config.TestenvConfig.from_env()`.

The Admin API is used as an internal testenv helper without a token
(Discussion §3.7, Phase 3 feasibility verified).
"""

import azentsadminclient
import azentspublicclient

from testenv.runtime_config import TestenvConfig


def public_client(config: TestenvConfig) -> azentspublicclient.ApiClient:
    """Public API client; callers pass auth tokens through `_headers`."""
    return azentspublicclient.ApiClient(
        configuration=azentspublicclient.Configuration(host=config.public_url),
    )


def admin_client(config: TestenvConfig) -> azentsadminclient.ApiClient:
    """Admin API client for internal testenv calls without a token."""
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(host=config.admin_url),
    )
