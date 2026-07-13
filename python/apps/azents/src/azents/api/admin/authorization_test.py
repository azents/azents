"""Admin API authorization boundary tests."""

from azents.app import create_dummy_admin_app

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
_UNAUTHENTICATED_OPERATIONS = {
    ("get", "/health/v1/readiness"),
    ("get", "/health/v1/liveness"),
    ("get", "/system/v1/bootstrap/status"),
    ("post", "/system/v1/bootstrap/first-admin"),
}


def test_every_operational_admin_api_declares_bearer_security() -> None:
    """Protect every Admin operation except infrastructure health probes."""
    paths = create_dummy_admin_app().openapi()["paths"]

    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            if (method, path) in _UNAUTHENTICATED_OPERATIONS:
                assert "security" not in operation, f"{method.upper()} {path}"
                continue
            assert operation.get("security") == [{"HTTPBearer": []}], (
                f"{method.upper()} {path}"
            )
