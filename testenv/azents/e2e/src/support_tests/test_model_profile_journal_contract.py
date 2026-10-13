"""Listener-free regressions for shared model-profile journal helpers."""

from collections.abc import Callable
from unittest.mock import Mock

import pytest
import requests

from tests.required.public import test_session_model_profile_api as profile_api

_JournalReader = Callable[[str], list[dict[str, object]]]
_READERS = [
    (profile_api._journal, "/v1/_requests"),
    (profile_api._image_generation_journal, "/v1/_image_generation_requests"),
]


def _response(text: str, *, status_code: int = 200) -> requests.Response:
    """Build a real HTTP response without opening a transport."""
    response = requests.Response()
    response.status_code = status_code
    response.url = "http://journal.test/fixture"
    response._content = text.encode()
    return response


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_journal_reader_uses_its_explicit_operation_on_the_base_url(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """Both current operations preserve their own base-URL callable purpose."""
    get = Mock(return_value=_response('[{"future":{"items":[null,false,0,""]}}]'))
    monkeypatch.setattr(profile_api.requests, "get", get)

    assert reader("http://journal.test:8080") == [
        {"future": {"items": [None, False, 0, ""]}}
    ]
    get.assert_called_once_with(f"http://journal.test:8080{path}", timeout=10)


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_journal_snapshots_compare_opaque_json_semantics_not_wire_format(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """Whitespace and object-key order do not become provider side effects."""
    first = _response('[{"unknown":{"b":[null,false,0],"a":"opaque"},"id":1}]')
    reordered = _response(
        '[\n  {"id": 1, "unknown": {"a": "opaque", "b": [null, false, 0]}}\n]'
    )
    changed = _response('[{"unknown":{"b":[null,true,0],"a":"opaque"},"id":1}]')
    get = Mock(side_effect=[first, reordered, changed])
    monkeypatch.setattr(profile_api.requests, "get", get)

    snapshot = reader("http://journal.test")
    assert first.content != reordered.content
    assert reader("http://journal.test") == snapshot
    assert reader("http://journal.test") != snapshot
    assert get.call_count == 3
    assert all(
        call.args == (f"http://journal.test{path}",) and call.kwargs == {"timeout": 10}
        for call in get.call_args_list
    )


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_empty_journal_is_an_opaque_valid_snapshot(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """An empty request list proves the same no-side-effect baseline as before."""
    get = Mock(return_value=_response("[]"))
    monkeypatch.setattr(profile_api.requests, "get", get)

    assert reader("http://journal.test") == []
    get.assert_called_once_with(f"http://journal.test{path}", timeout=10)


@pytest.mark.parametrize(("reader", "path"), _READERS)
@pytest.mark.parametrize("payload", ['{"private":"must-not-be-reflected"}', "[false]"])
def test_non_object_list_journal_fails_without_reflecting_opaque_contents(
    monkeypatch: pytest.MonkeyPatch,
    reader: _JournalReader,
    path: str,
    payload: str,
) -> None:
    """Preserve the boundary shape check without adding provider-field schemas."""
    get = Mock(return_value=_response(payload))
    monkeypatch.setattr(profile_api.requests, "get", get)

    with pytest.raises(AssertionError) as failure:
        reader("http://journal.test")
    assert str(failure.value) == "Provider journal was not an object list."
    get.assert_called_once_with(f"http://journal.test{path}", timeout=10)


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_http_failure_precedes_journal_decoding(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """A failed HTTP operation cannot masquerade as an empty provider journal."""
    get = Mock(return_value=_response("not JSON", status_code=404))
    monkeypatch.setattr(profile_api.requests, "get", get)

    with pytest.raises(requests.HTTPError):
        reader("http://journal.test")
    get.assert_called_once_with(f"http://journal.test{path}", timeout=10)


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_invalid_json_failure_is_not_disguised_as_a_snapshot(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """Malformed successful responses retain the requests JSON error boundary."""
    get = Mock(return_value=_response("not JSON"))
    monkeypatch.setattr(profile_api.requests, "get", get)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        reader("http://journal.test")
    get.assert_called_once_with(f"http://journal.test{path}", timeout=10)


@pytest.mark.parametrize(("reader", "path"), _READERS)
def test_transport_failure_propagates_without_a_fallback_url(
    monkeypatch: pytest.MonkeyPatch, reader: _JournalReader, path: str
) -> None:
    """Each reader makes only its authoritative current operation request."""
    failure = requests.ConnectionError("fixture transport failure")
    get = Mock(side_effect=failure)
    monkeypatch.setattr(profile_api.requests, "get", get)

    with pytest.raises(requests.ConnectionError) as caught:
        reader("http://journal.test")
    assert caught.value is failure
    get.assert_called_once_with(f"http://journal.test{path}", timeout=10)
