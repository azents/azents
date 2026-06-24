"""testenv run settings with explicit dependency injection.

Do not mutate ``os.environ`` at import time. This module does not call
``load_dotenv`` globally; instead, ``TestenvConfig.load()`` reads `.env` into an
internal ``env_vars`` dict.

The config is passed to :class:`TCRunnerOptions` / :func:`run_setup`, and run
paths pass selected values to subprocesses through ``env_extra``. Setup and TC
handlers should access credentials such as ``BEDROCK_*`` and
``TESTENV_AZENTS_FUNNEL_URL`` through this explicit path.

Design goals:

* Avoid ambient ``os.environ`` mutation so callers control the environment.
* Allow multiple isolated configs in tests, including sharded tests.
* Make subprocess environment values explicit and auditable.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

logger = logging.getLogger(__name__)


def default_env_path() -> Path:
    """Return the default ``testenv/azents/.env`` path from ``config.py``."""
    return Path(__file__).resolve().parent.parent / ".env"


@dataclass
class TestenvConfig:
    """Environment settings passed to subprocesses.

    :param env_vars: ``key=value`` pairs passed to setup / TC handler
        subprocesses. Usually loaded from `.env` plus optional CLI overrides.
    :param env_path: path to the settings file that was loaded, for diagnostics.
    """

    env_vars: dict[str, str] = field(default_factory=dict)
    env_path: Path | None = None

    # --------------------------------------------------------------------- load

    @classmethod
    def load(
        cls,
        env_path: Path | None = None,
        *,
        include_process_env: bool = False,
    ) -> TestenvConfig:
        """Load a `.env` file and return :class:`TestenvConfig`.

        :param env_path: `.env` path to load. ``None`` uses :func:`default_env_path`.
        :param include_process_env: when True, fill missing keys from current
            ``os.environ``. This is useful for CI-provided environment values.
            Defaults to False for isolation.
        :returns: :class:`TestenvConfig`.
        """
        path = env_path if env_path is not None else default_env_path()
        loaded: dict[str, str] = {}
        if path.exists():
            parsed = dotenv_values(path)
            for key, value in parsed.items():
                if value is not None:
                    loaded[key] = value
            logger.info("TestenvConfig loaded %d keys from %s", len(loaded), path)
        else:
            logger.warning("TestenvConfig env file not found: %s (using empty config)", path)

        if include_process_env:
            for key, value in os.environ.items():
                loaded.setdefault(key, value)

        return cls(env_vars=loaded, env_path=path)

    # --------------------------------------------------------------------- api

    def get(self, key: str, default: str | None = None) -> str | None:
        """Look up a config value; missing keys may return None."""
        return self.env_vars.get(key, default)

    def require(self, key: str) -> str:
        """Return a required key or raise ``RuntimeError`` when missing."""
        value = self.env_vars.get(key)
        if value is None or value == "":
            raise RuntimeError(f"TestenvConfig: required key {key!r} missing")
        return value

    def merge_into_env(self, base: dict[str, str]) -> dict[str, str]:
        """Merge config values into a base env dict without overwriting existing keys.

        Subprocess callers usually use ``env = dict(os.environ);
        config.merge_into_env(env); ...``. Existing keys in ``os.environ`` win,
        which lets CI-provided values override `.env` values.
        """
        for key, value in self.env_vars.items():
            base.setdefault(key, value)
        return base

    def as_env_extra(self) -> dict[str, str]:
        """Return a standalone env dict for subprocess handlers.

        Use this when the caller wants to own the full environment instead of
        merging with ``os.environ``. The returned dict is a copy and safe to
        mutate.
        """
        return dict(self.env_vars)
