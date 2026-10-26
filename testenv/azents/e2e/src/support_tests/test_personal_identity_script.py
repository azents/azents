"""Personal ownership proves identity without replaying repository access matrices."""

from dataclasses import dataclass

import pytest

from support import image_generation_openai_proxy as proxy


@dataclass(frozen=True)
class _Call:
    call_id: str
    name: str
    arguments: dict[str, object]


class _Handler(proxy._Handler):
    def __init__(self) -> None:
        self.path = "/v1/responses"
        self.call: _Call | None = None
        self.text: str | None = None

    def _write_function_call_response(
        self,
        request: proxy._ModelRequestInput,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        self.call = _Call(call_id, name, arguments)

    def _write_text_response(
        self,
        request: proxy._ModelRequestInput,
        text: str,
        *,
        response_id: str,
    ) -> None:
        self.text = text


def _request(
    *, kind: str, completed: tuple[str, ...], sparse: bool, tools: tuple[str, ...]
) -> proxy._ModelRequest:
    items: list[dict[str, object]] = []
    if not sparse:
        items.append({"role": "user", "content": f"GitHub User Toolkit E2E {kind}"})
    items.extend(
        {"type": "function_call_output", "call_id": call_id, "output": "{}"}
        for call_id in completed
    )
    return proxy._decode_model_request(
        {
            "input": items,
            "tools": [{"type": "function", "name": name} for name in tools],
        }
    )


@pytest.mark.parametrize("sparse", [False, True])
def test_personal_identity_terminates_after_its_only_provider_call(
    sparse: bool,
) -> None:
    handler = _Handler()
    prefix = "call_github_user_personal"
    handler._dispatch_model_request(
        _request(
            kind="personal",
            completed=(prefix + "_search",),
            sparse=sparse,
            tools=("github_user__get_me", "github_user__get_file_contents"),
        ),
        b"",
    )
    assert handler.call == _Call(prefix + "_0", "github_user__get_me", {})
    handler = _Handler()
    handler._dispatch_model_request(
        _request(
            kind="personal",
            completed=(prefix + "_0",),
            sparse=sparse,
            tools=("github_user__get_me", "github_user__get_file_contents"),
        ),
        b"",
    )
    assert handler.call is None
    assert handler.text == "GITHUB_USER_E2E_COMPLETED_personal"


def test_personal_discovery_uses_an_isolated_call_id() -> None:
    handler = _Handler()
    handler._dispatch_model_request(
        _request(kind="personal", completed=(), sparse=False, tools=("tool_search",)),
        b"",
    )
    assert handler.call == _Call(
        "call_github_user_personal_search",
        "tool_search",
        {"query": "github_user__get_me", "limit": 8},
    )


def test_github_repository_matrix_retains_all_five_operations() -> None:
    completed: list[str] = []
    for index, owner in enumerate(
        (None, "connected-user", "research-team", "ops-team", "restricted-team")
    ):
        handler = _Handler()
        handler._dispatch_model_request(
            _request(
                kind="mcp",
                completed=tuple(completed),
                sparse=index > 0,
                tools=("github_user__get_me", "github_user__get_file_contents"),
            ),
            b"",
        )
        call_id = f"call_github_user_mcp_{index}"
        assert handler.call == _Call(
            call_id,
            "github_user__get_me"
            if owner is None
            else "github_user__get_file_contents",
            {}
            if owner is None
            else {"owner": owner, "repo": "fixture-repo", "path": "README.md"},
        )
        completed.append(call_id)
    handler = _Handler()
    handler._dispatch_model_request(
        _request(kind="mcp", completed=tuple(completed), sparse=True, tools=()),
        b"",
    )
    assert handler.call is None
    assert handler.text == "GITHUB_USER_E2E_COMPLETED_mcp"
