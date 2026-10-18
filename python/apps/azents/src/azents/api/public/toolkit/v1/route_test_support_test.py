"""Focused paths preserve custom routing, validation and production schemas."""

from fastapi import FastAPI

from azents.api.public.toolkit.v1.github_setup import router as setup_router
from azents.api.public.toolkit.v1.github_user_creation import router as creation_router
from azents.api.public.toolkit.v1.route_test_support import focused_toolkit_app
from azents.utils.fastapi.route import generate_short_operation_id


def test_focused_toolkit_operations_match_complete_actual_routers() -> None:
    full = FastAPI(generate_unique_id_function=generate_short_operation_id)
    full.include_router(setup_router)
    full.include_router(creation_router)
    complete = full.openapi()
    for router, suffix in (
        (setup_router, "/github/setup-verification"),
        (setup_router, "/github/setup-app"),
        (creation_router, "/github-user-creations/confirm"),
        (creation_router, "/github-user-creations/{attempt_id}/app"),
    ):
        app = focused_toolkit_app((router, suffix))
        spec = app.openapi()
        expected = {
            path: operation
            for path, operation in complete["paths"].items()
            if path.endswith(suffix)
        }
        assert len(expected) == 2  # Workspace and Agent authority variants.
        assert spec["paths"] == expected
        for name, schema in spec["components"]["schemas"].items():
            assert schema == complete["components"]["schemas"][name]


def test_focused_toolkit_apps_have_fresh_overrides_and_schema_caches() -> None:
    first = focused_toolkit_app((setup_router, "/github/setup-verification"))
    second = focused_toolkit_app((setup_router, "/github/setup-verification"))
    assert first is not second
    assert first.dependency_overrides is not second.dependency_overrides
    assert first.openapi() is not second.openapi()
