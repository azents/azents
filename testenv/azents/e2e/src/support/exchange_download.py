"""Exchange GET handoff verification for the observed local HTTPS fixture."""

from dataclasses import dataclass
from urllib.parse import urlsplit

import requests


@dataclass(frozen=True)
class _HttpsOrigin:
    hostname: str
    port: int


def _https_origin(url: str, *, endpoint: bool) -> _HttpsOrigin:
    """Validate one absolute HTTPS URL without exposing its capability."""
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise AssertionError("Fixture Exchange URL contains invalid characters.")
    if "\\" in url or "\x7f" in url:
        raise AssertionError("Fixture Exchange URL contains invalid characters.")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise AssertionError("Fixture Exchange URL is invalid.") from None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise AssertionError("Fixture Exchange URL requires a plain HTTPS origin.")
    if endpoint and (parsed.path not in ("", "/") or parsed.query):
        raise AssertionError("Fixture Exchange endpoint must contain only its origin.")
    return _HttpsOrigin(hostname=hostname, port=443 if port is None else port)


def download_fixture_exchange_file(
    *,
    server_url: str,
    access_token: str,
    attachment_id: str,
    storage_endpoint_url: str,
) -> bytes:
    """Verify the API handoff and fetch bytes from the exact fixture origin.

    :param server_url: Public API fixture base URL.
    :param access_token: Requester's public API credential.
    :param attachment_id: Published Exchange attachment ID.
    :param storage_endpoint_url: Observed local browser S3 fixture HTTPS endpoint.
    :returns: Storage response bytes, without request or capability evidence.
    :raises AssertionError: Invalid handoff, origin, or storage response.
    """
    fixture_origin = _https_origin(storage_endpoint_url, endpoint=True)
    try:
        with requests.get(
            f"{server_url}/chat/v1/exchange-files/{attachment_id}/download",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
            allow_redirects=False,
            verify=True,
        ) as handoff:
            if handoff.status_code != 302:
                raise AssertionError("Exchange API must return an authorized 302.")
            if handoff.content != b"":
                raise AssertionError("Exchange API handoff body must be empty.")
            if handoff.headers.get("Cache-Control") != "no-store":
                raise AssertionError("Exchange API handoff must disable caching.")
            if handoff.headers.get("Referrer-Policy") != "no-referrer":
                raise AssertionError("Exchange API handoff must disable referrers.")
            location = handoff.headers.get("Location")
            if not location:
                raise AssertionError("Exchange API handoff requires a Location.")
    except requests.exceptions.RequestException:
        raise AssertionError("Exchange API handoff request failed.") from None
    if _https_origin(location, endpoint=False) != fixture_origin:
        raise AssertionError("Exchange handoff must use the observed fixture origin.")
    try:
        # The local certificate has a DNS SAN; signing uses the Docker gateway IP.
        # Only this exact observed HTTPS fixture origin permits verify=False.
        with requests.get(
            location,
            timeout=10,
            allow_redirects=False,
            verify=False,
        ) as download:
            if download.status_code != 200:
                raise AssertionError("Fixture Exchange storage GET must return 200.")
            return download.content
    except requests.exceptions.RequestException:
        raise AssertionError("Fixture Exchange storage GET failed.") from None
