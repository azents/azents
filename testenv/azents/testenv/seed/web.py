"""Stage 4 azents-web QA browser storage-state helper.

Browser login flows such as TC-WEB-002 save authenticated storage state
(cookies + localStorage) under ``runs/_state/``. A QA runner such as Claude Code
can save Playwright tool results from ``browser_evaluate`` / ``browser_run_code``
and later load them to restore browser session state.

Stage 4 assumes Claude Code runs outside this module (Discussion #2441 P1). This
helper only manages the storage-state file lifecycle; it does not attach a
Playwright toolkit.

Related document: ``docs/azents/design/stage4-web.md``
"""

from dataclasses import dataclass, field
from pathlib import Path

from testenv.runtime_config import TestenvConfig

# Default cache root — testenv/azents/runs/_state/.
# runs/ is gitignored and retained with .gitkeep.
DEFAULT_STATE_CACHE_ROOT = Path("runs") / "_state"


@dataclass(frozen=True)
class StorageState:
    """Browser storage-state helper used by ``TestenvClient.web``.

    Keys are typically derived from user email.
    """

    config: TestenvConfig
    cache_root: Path = field(default_factory=lambda: DEFAULT_STATE_CACHE_ROOT)

    def path(self, key: str) -> Path:
        """Return the storage-state file path for ``key``."""
        return self.cache_root / f"{key}.json"

    def has(self, key: str) -> bool:
        """Return whether storage state exists for ``key``."""
        return self.path(key).is_file()

    def save(self, key: str, state_json: str) -> None:
        """Save raw browser storage-state JSON.

        ``state_json`` is the JSON string returned by Playwright tools such as
        ``browser_evaluate`` / ``browser_run_code``. This helper intentionally
        stores the raw string.
        """
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(state_json)

    def load(self, key: str) -> str:
        """Return browser storage state as a raw JSON string.

        Raises ``FileNotFoundError`` when the file is missing.
        """
        return self.path(key).read_text()
