"""Schema evidence copies cannot mutate later test contracts."""

import json
from typing import Any


def test_full_public_openapi_fixture_deeply_isolates_schema_assertions(
    full_public_openapi: dict[str, Any],
    _full_public_openapi_source: dict[str, Any],
) -> None:
    """Verify the actual fixture boundary, not only Python copy semantics."""
    before = json.dumps(_full_public_openapi_source, sort_keys=True)
    assert full_public_openapi == _full_public_openapi_source
    assert full_public_openapi is not _full_public_openapi_source
    path = next(iter(full_public_openapi["paths"]))
    assert (
        full_public_openapi["paths"][path]
        is not (_full_public_openapi_source["paths"][path])
    )
    full_public_openapi["paths"][path].clear()
    full_public_openapi["components"]["schemas"].clear()
    assert json.dumps(_full_public_openapi_source, sort_keys=True) == before
