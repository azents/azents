"""Deterministic GitHub validation proxy tests."""

from collections.abc import Generator
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from support.github_validation_proxy import Handler


@pytest.fixture
def github_proxy_url() -> Generator[str, None, None]:
    """Run the proxy on an ephemeral host port."""
    Handler.scenario = "valid"
    Handler.app_request_count = 0
    Handler.oauth_request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_valid_and_invalid_oauth_scenarios_are_controllable(
    github_proxy_url: str,
) -> None:
    """The proxy returns bounded provider classifications and request counts."""
    app_response = requests.get(f"{github_proxy_url}/app", timeout=5)
    assert app_response.status_code == 200
    assert app_response.json() == {
        "id": 123,
        "client_id": "Iv1.azents-test",
        "slug": "azents-test",
    }

    scenario_response = requests.post(
        f"{github_proxy_url}/__testenv/scenario",
        json={"scenario": "invalid_oauth"},
        timeout=5,
    )
    assert scenario_response.status_code == 200

    oauth_response = requests.post(
        f"{github_proxy_url}/login/oauth/access_token",
        json={"client_secret": "must-not-be-reflected"},
        timeout=5,
    )
    assert oauth_response.status_code == 200
    assert oauth_response.json()["error"] == "incorrect_client_credentials"
    assert "must-not-be-reflected" not in oauth_response.text

    state_response = requests.get(
        f"{github_proxy_url}/__testenv/state",
        timeout=5,
    )
    assert state_response.status_code == 200
    assert state_response.json() == {
        "scenario": "invalid_oauth",
        "app_request_count": 0,
        "oauth_request_count": 1,
    }
