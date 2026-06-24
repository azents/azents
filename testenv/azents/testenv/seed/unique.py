"""Unique suffix helper.

Creates short 8-hex suffixes for test objects, mirroring the old E2E
`utils.unique()` helper.
"""

import uuid


def unique() -> str:
    """Return an 8-hex suffix."""
    return uuid.uuid4().hex[:8]
