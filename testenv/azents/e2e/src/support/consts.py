"""t t."""

from pathlib import Path

#: t t (testenv/azents/e2e)
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()

#: t t (azents)
REPOSITORY_ROOT = PROJECT_ROOT.parent.parent.parent.absolute()

#: Lowered, testenv-only general-file policy for inexpensive boundary journeys.
E2E_GENERAL_FILE_MAXIMUM_BYTES = 1024 * 1024
