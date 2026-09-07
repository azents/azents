"""Tests for the azents-web devserver lifecycle helper."""

from pathlib import Path

import pytest

import testenv.devserverlib.web as web


def test_start_web_uses_ipv4_loopback_for_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Node server calls use the IPv4 listener exposed by local Uvicorn."""
    state_dir = tmp_path / ".state"
    web_log = state_dir / "web.log"
    typescript_dir = tmp_path / "typescript"
    web_dir = typescript_dir / "apps" / "azents-web"
    web_dir.mkdir(parents=True)
    created: list[dict[str, object]] = []

    monkeypatch.setattr(web, "STATE_DIR", state_dir)
    monkeypatch.setattr(web, "WEB_LOG_FILE", web_log)
    monkeypatch.setattr(web, "TYPESCRIPT_DIR", typescript_dir)
    monkeypatch.setattr(web, "AZENTS_WEB_DIR", web_dir)
    monkeypatch.setattr(web, "is_web_running", lambda: False)
    monkeypatch.setattr(web.tmux, "new_session", lambda **kwargs: created.append(kwargs))
    monkeypatch.setattr(web.tmux, "pipe_pane_to_file", lambda *_: None)

    web.start_web()

    assert created[0]["env"] == {
        "PUBLIC_API_URL": "http://127.0.0.1:8010",
        "INTERNAL_API_URL": "http://127.0.0.1:8010",
        "NODE_ENV": "development",
    }
