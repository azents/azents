#!/usr/bin/env python3
"""Preflight checks.

Checks prerequisites for the Azents local test environment. See `README.md` and
`docs/azents/design/local-fullstack-test-env.md` for details.

Usage:
    python testenv/azents/preflight.py
"""

import sys

from testenv.checks import all_checks
from testenv.checks.output import Formatter
from testenv.checks.runner import Runner


def main() -> int:
    return Runner(all_checks(), Formatter.from_stdout()).run()


if __name__ == "__main__":
    sys.exit(main())
