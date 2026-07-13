"""Admin API authorization boundary tests."""

from azents.app import create_dummy_admin_app

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
_HEALTH_PREFIX = "/health/v1/"


def test_every_operational_admin_api_declares_bearer_security() -> None:
    """Protect every Admin operation except infrastructure health probes."""
    paths = create_dummy_admin_app().openapi()["paths"]

    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            if path.startswith(_HEALTH_PREFIX):
                assert "security" not in operation, f"{method.upper()} {path}"
                continue
            assert operation.get("security") == [{"HTTPBearer": []}], (
                f"{method.upper()} {path}"
            )
