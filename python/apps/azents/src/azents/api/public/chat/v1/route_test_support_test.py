"""Focused apps retain exact production Chat operation and schema contracts."""

from fastapi import FastAPI

from azents.api.public.chat.v1 import mount
from azents.api.public.chat.v1.route_test_support import focused_chat_app
from azents.utils.fastapi.route import as_route_mounter, generate_short_operation_id


def test_focused_chat_paths_match_complete_production_router() -> None:
    app = FastAPI(generate_unique_id_function=generate_short_operation_id)
    mount(as_route_mounter(app))
    complete = app.openapi()
    for path in (
        "/sessions/{session_id}/model-profile",
        "/sessions/{session_id}/inputs",
    ):
        focused = focused_chat_app(path).openapi()
        mounted_path = "/chat/v1" + path
        assert set(focused["paths"]) == {mounted_path}
        assert focused["paths"][mounted_path] == complete["paths"][mounted_path]
        for name, schema in focused["components"]["schemas"].items():
            assert schema == complete["components"]["schemas"][name]


def test_focused_chat_apps_do_not_share_dependency_overrides_or_openapi_cache() -> None:
    first = focused_chat_app("/sessions/{session_id}/model-profile")
    second = focused_chat_app("/sessions/{session_id}/model-profile")
    assert first is not second
    assert first.dependency_overrides is not second.dependency_overrides
    assert first.openapi() is not second.openapi()
