"""testenv/azents integration settings.

`seed.*` and `live.*` helpers share this frozen dataclass for environment-driven
endpoints. Environment keys are read in one place so helpers do not rely on
ambient global configuration.

There is no implicit default instance. Call `TestenvConfig.from_env()` at the
edge, then pass the resulting `TestenvConfig` through dependency injection. This
makes tests able to pass explicit values.

Example:
    from testenv.runtime_config import TestenvConfig
    from testenv.seed.client import public_client

    cfg = TestenvConfig.from_env()
    client = public_client(cfg)            # DI

Defaults point to the localhost ports used by testenv compose. Environment
variables can override them.
"""

import os
from dataclasses import dataclass

_DEFAULT_PUBLIC_URL = "http://localhost:8010"
_DEFAULT_ADMIN_URL = "http://localhost:8011"
_DEFAULT_TESTENV_API_URL = "http://localhost:8012"


@dataclass(frozen=True)
class TestenvConfig:
    """testenv runtime settings."""

    public_url: str
    admin_url: str
    testenv_api_url: str

    @classmethod
    def from_env(cls) -> "TestenvConfig":
        """Read environment variables and return a runtime config dataclass.

        Keep environment reads at the edge: callers invoke `from_env()` once and
        pass the config through DI to helpers.
        """
        return cls(
            public_url=os.environ.get("TESTENV_AZENTS_PUBLIC_URL", _DEFAULT_PUBLIC_URL),
            admin_url=os.environ.get("TESTENV_AZENTS_ADMIN_URL", _DEFAULT_ADMIN_URL),
            testenv_api_url=os.environ.get(
                "TESTENV_AZENTS_TESTENV_API_URL", _DEFAULT_TESTENV_API_URL
            ),
        )
