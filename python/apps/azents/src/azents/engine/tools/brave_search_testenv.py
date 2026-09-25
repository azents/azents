"""Deterministic, in-process Brave transport used only by the testenv stack."""

from io import BytesIO

import httpx
from PIL import Image

_API_HOST = "api.search.brave.com"
_IMAGE_HOST = "imgs.search.brave.com"
_VALID_KEY = "brave-e2e-valid"
_REVOKED_KEY = "brave-e2e-revoked"
_RATE_LIMITED_KEY = "brave-e2e-limited"
_NO_ENTITLEMENT_KEY = "brave-e2e-no-entitlement"
_TIMEOUT_KEY = "brave-e2e-timeout"


def _image_bytes() -> bytes:
    """Build the same small decoded-image fixture for each testenv request."""
    output = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    return output.getvalue()


_IMAGE_BYTES = _image_bytes()


def _fixture_response(request: httpx.Request) -> httpx.Response:
    """Respond to fixed Brave hosts only; fail closed on an unknown request."""
    if request.url.host == _IMAGE_HOST and request.url.path in {
        "/brave-e2e-one.png",
        "/brave-e2e-two.png",
        "/brave-e2e-invalid.png",
    }:
        if "x-subscription-token" in request.headers:
            return httpx.Response(500)
        if request.url.path == "/brave-e2e-invalid.png":
            return httpx.Response(
                200, content=b"not an image", headers={"content-type": "image/png"}
            )
        return httpx.Response(
            200, content=_IMAGE_BYTES, headers={"content-type": "image/png"}
        )
    if request.url.host != _API_HOST:
        return httpx.Response(404)
    key = request.headers.get("x-subscription-token")
    if key == _TIMEOUT_KEY:
        raise httpx.ConnectTimeout("Brave testenv timeout", request=request)
    if key == _NO_ENTITLEMENT_KEY:
        return httpx.Response(403)
    if key == _REVOKED_KEY or key not in {
        _VALID_KEY,
        _RATE_LIMITED_KEY,
    }:
        return httpx.Response(401)
    if key == _RATE_LIMITED_KEY:
        return httpx.Response(429)
    query = request.url.params.get("q")
    if not query:
        return httpx.Response(400)
    count = int(request.url.params.get("count", "10"))
    if request.url.path == "/res/v1/web/search":
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Brave fixture Web result",
                            "url": "https://example.org/brave/web",
                            "description": "Deterministic Web source",
                            "page_age": "2026-09-24",
                        }
                    ][:count]
                }
            },
        )
    if request.url.path == "/res/v1/llm/context":
        return httpx.Response(
            200,
            json={
                "grounding": {
                    "generic": [
                        {
                            "title": "Brave fixture Context result",
                            "url": "https://example.org/brave/context",
                            "snippets": ["Deterministic context source"],
                        }
                    ][:count]
                }
            },
        )
    if request.url.path in {"/res/v1/news/search", "/res/v1/videos/search"}:
        kind = "news" if request.url.path == "/res/v1/news/search" else "videos"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": f"Brave fixture {kind} result",
                        "url": f"https://example.org/brave/{kind}",
                        "description": f"Deterministic {kind} source",
                        "profile": {"name": "Fixture publisher"},
                    }
                ][:count]
            },
        )
    if request.url.path == "/res/v1/images/search":
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": f"Brave fixture image {index}",
                        "url": f"https://example.org/brave/image-page-{index}",
                        "properties": {
                            "url": f"https://example.org/brave/original-{index}.png"
                        },
                        "thumbnail": {
                            "src": f"https://{_IMAGE_HOST}/brave-e2e-{word}.png"
                        },
                    }
                    for index, word in enumerate(("one", "two", "invalid"), start=1)
                ][:count]
            },
        )
    return httpx.Response(404)


def make_brave_testenv_transport() -> httpx.MockTransport:
    """Inject a fixed-host test fixture only while testenv is explicitly enabled."""
    return httpx.MockTransport(_fixture_response)
