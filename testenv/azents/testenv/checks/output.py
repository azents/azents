"""Preflight output formatting.

Uses colored Unicode symbols on TTY output and ASCII status labels otherwise.
The ``NO_COLOR`` environment variable disables color.
"""

import os
import sys
from dataclasses import dataclass

from .base import Status

# ANSI escape codes
_RESET = "\x1b[0m"
_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_YELLOW = "\x1b[33m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"


@dataclass
class Formatter:
    """Formatter with optional TTY color support.

    - TTY: Unicode symbols plus ANSI colors.
    - non-TTY or ``NO_COLOR``: ASCII labels such as ``[PASS]``.
    """

    use_color: bool

    @classmethod
    def from_stdout(cls) -> "Formatter":
        """Create a formatter configured from stdout TTY state."""
        is_tty = sys.stdout.isatty()
        no_color = bool(os.environ.get("NO_COLOR"))
        return cls(use_color=is_tty and not no_color)

    def status_symbol(self, status: Status) -> str:
        """Return the display symbol for a status."""
        if self.use_color:
            symbols = {
                Status.PASS: f"{_GREEN}✓{_RESET}",
                Status.FAIL: f"{_RED}✗{_RESET}",
                Status.WARN: f"{_YELLOW}⚠{_RESET}",
                Status.SKIP: f"{_DIM}⊘{_RESET}",
            }
        else:
            symbols = {
                Status.PASS: "[PASS]",
                Status.FAIL: "[FAIL]",
                Status.WARN: "[WARN]",
                Status.SKIP: "[SKIP]",
            }
        return symbols[status]

    def category_header(self, category: str) -> str:
        """Return a category header line."""
        title = category.replace("_", " ").title()
        if self.use_color:
            return f"\n{_BOLD}{title}{_RESET}"
        return f"\n== {title} =="

    def summary(self, total: int, passed: int, failed: int, skipped: int) -> str:
        """Return the final summary line."""
        if failed == 0 and skipped == 0:
            msg = f"All checks passed ({passed}/{total})"
            if self.use_color:
                return f"\n{_GREEN}{msg}{_RESET}"
            return f"\n{msg}"
        parts = [f"{passed} passed", f"{failed} failed"]
        if skipped:
            parts.append(f"{skipped} skipped")
        msg = f"Result: {', '.join(parts)} (of {total})"
        if self.use_color:
            color = _RED if failed else _YELLOW
            return f"\n{color}{msg}{_RESET}"
        return f"\n{msg}"
