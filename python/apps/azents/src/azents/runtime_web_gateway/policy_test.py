"""Proxy-consumed field and application-header preservation tests."""

import pytest

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.runtime_web_gateway.policy import (
    RuntimeWebPolicyError,
    normalize_request_headers,
    normalize_response_headers,
    parse_target_host,
)
from azents.runtime_web_gateway.settings import RuntimeWebGatewayConfig

_CONFIG = RuntimeWebGatewayConfig(
    enabled=True,
    auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
    main_web_origin="https://app.example.com",
    broker_origin="https://auth.services.example.net",
    service_suffix="services.example.net",
    cookie_domain="services.example.net",
    identity_cookie_name="__Http-Azents-Runtime-Web",
    identity_lifetime_seconds=1_800,
    request_header_bytes=32 * 1024,
    request_body_bytes=64 * 1024 * 1024,
    permissions_policy="camera=()",
)


def test_host_parser_accepts_one_lowercase_endpoint_label_or_broker() -> None:
    endpoint = parse_target_host("abc123.services.example.net", config=_CONFIG)
    broker = parse_target_host("auth.services.example.net", config=_CONFIG)

    assert endpoint.endpoint_label == "abc123"
    assert not endpoint.broker
    assert broker.broker

    for host in (
        "ABC.services.example.net",
        "a.b.services.example.net",
        "services.example.net",
        "abc.other.example.net",
        "abc.services.example.net,attacker.example",
    ):
        with pytest.raises(RuntimeWebPolicyError):
            parse_target_host(host, config=_CONFIG)


@pytest.mark.parametrize(
    "origin",
    [b"null", b"https://external.example.com", b"file://", b"https://bad:port"],
)
def test_application_origin_values_are_preserved(origin: bytes) -> None:
    headers = normalize_request_headers(
        ((b"Origin", origin), (b"Referer", origin)),
        port=8080,
        websocket=False,
        maximum_bytes=32 * 1024,
    )

    assert (b"Origin", origin) in headers
    assert (b"Referer", origin) in headers


def test_header_normalization_strips_platform_authority_and_preserves_app_policy() -> (
    None
):
    request_headers = normalize_request_headers(
        (
            (b"Cookie", b"__Http-Azents-Runtime-Web=secret; app=value"),
            (b"Authorization", b"Bearer application-token"),
            (b"Origin", b"https://abc.services.example.net"),
            (b"Connection", b"keep-alive"),
            (b"Sec-WebSocket-Key", b"browser-owned"),
            (b"Sec-WebSocket-Extensions", b"permessage-deflate"),
        ),
        port=8080,
        websocket=True,
        maximum_bytes=32 * 1024,
    )
    response_headers = normalize_response_headers(
        (
            (b"Set-Cookie", b"__Http-Azents-Runtime-Web=attacker"),
            (b"Set-Cookie", b"app=value; Domain=localhost; Path=/"),
            (b"Location", b"http://127.0.0.1:8080/next?value=1"),
            (b"Access-Control-Allow-Origin", b"*"),
            (b"Cache-Control", b"public, max-age=3600"),
        ),
        target_origin="https://abc.services.example.net",
        port=8080,
        websocket=False,
    )

    assert (b"host", b"localhost:8080") in request_headers
    assert (b"Cookie", b"app=value") in request_headers
    assert not any(
        name.lower().startswith(b"sec-websocket-") for name, _value in request_headers
    )
    assert (b"Authorization", b"Bearer application-token") in request_headers
    assert ("Set-Cookie", "app=value; Path=/") in response_headers
    assert (
        "Location",
        "https://abc.services.example.net/next?value=1",
    ) in response_headers
    assert ("Cache-Control", "public, max-age=3600") in response_headers
    assert ("Access-Control-Allow-Origin", "*") in response_headers
    assert (b"Origin", b"https://abc.services.example.net") in request_headers
    assert not any(
        name in {"Referrer-Policy", "Cross-Origin-Opener-Policy", "Permissions-Policy"}
        for name, _value in response_headers
    )
    assert not any(
        name == "Set-Cookie" and "__Http-Azents" in value
        for name, value in response_headers
    )


@pytest.mark.parametrize("websocket", [False, True])
def test_repeated_application_cookies_keep_order_and_exact_values(
    websocket: bool,
) -> None:
    headers = normalize_request_headers(
        (
            (
                b"Cookie",
                b'__Http-Azents-Runtime-Web=platform; session="a=b"; session=second',
            ),
            (
                b"Cookie",
                b"az-token=platform; az-token-app=lookalike; __Host-session=app",
            ),
            (b"Cookie", b"__Host-Azents-Access=platform"),
            (b"Cookie", b"__Host-Azents-App=owned; AZ-TOKEN=case-sensitive"),
        ),
        port=8080,
        websocket=websocket,
        maximum_bytes=32768,
    )
    assert headers == (
        (b"host", b"localhost:8080"),
        (b"Cookie", b'session="a=b"; session=second'),
        (b"Cookie", b"az-token-app=lookalike; __Host-session=app"),
        (b"Cookie", b"__Host-Azents-App=owned; AZ-TOKEN=case-sensitive"),
    )


@pytest.mark.parametrize("websocket", [False, True])
def test_connection_nominated_fields_are_consumed_in_both_directions(
    websocket: bool,
) -> None:
    headers = (
        (b"X-Hop-One", b"consume"),
        (b"Connection", b"keep-alive, X-Hop-One"),
        (b"connection", b" X-HOP-TWO "),
        (b"x-hop-two", b"consume"),
        (b"Proxy-Connection", b"keep-alive"),
        (b"Authorization", b"Bearer app"),
        (b"WWW-Authenticate", b"Basic realm=app"),
        (b"Origin", b"https://abc.services.example.net"),
        (b"Referer", b"https://abc.services.example.net/login?next=home"),
        (b"X-App", b"one"),
        (b"X-App", b"two"),
    )
    forwarded = headers[5:]
    assert normalize_request_headers(
        headers,
        port=8080,
        websocket=websocket,
        maximum_bytes=32768,
    ) == ((b"host", b"localhost:8080"), *forwarded)
    assert normalize_response_headers(
        iter(headers),
        target_origin="https://abc.services.example.net",
        port=8080,
        websocket=websocket,
    ) == tuple((name.decode(), value.decode()) for name, value in forwarded)


@pytest.mark.parametrize("websocket", [False, True])
def test_websocket_fields_are_consumed_only_for_regenerated_handshakes(
    websocket: bool,
) -> None:
    headers = (
        (b"Sec-WebSocket-Key", b"key"),
        (b"Sec-WebSocket-Accept", b"accept"),
        (b"Sec-WebSocket-Extensions", b"permessage-deflate"),
        (b"Sec-WebSocket-Version", b"13"),
        (b"Sec-WebSocket-Protocol", b"chat.v1"),
        (b"Content-Length", b"0"),
    )
    request = normalize_request_headers(
        headers,
        port=8080,
        websocket=websocket,
        maximum_bytes=32768,
    )
    assert request == (
        (b"host", b"localhost:8080"),
        *(headers[4:5] if websocket else headers),
    )
    response = normalize_response_headers(
        headers,
        target_origin="https://abc.services.example.net",
        port=8080,
        websocket=websocket,
    )
    assert response == (
        ()
        if websocket
        else tuple((name.decode(), value.decode()) for name, value in headers)
    )


def test_only_exact_platform_set_cookie_names_are_reserved() -> None:
    cookies = (
        (b"Set-Cookie", b"az-token=platform; Path=/"),
        (b"Set-Cookie", b"__Http-Azents-Runtime-Web=platform; Path=/"),
        (b"Set-Cookie", b'session="a=b";  Path=/; HttpOnly'),
        (b"Set-Cookie", b"session=second; Path=/other"),
        (b"Set-Cookie", b"az-token-app=owned; Domain=localhost.example"),
        (b"Set-Cookie", b"__Host-Azents-App=owned; Secure; Path=/"),
    )
    assert normalize_response_headers(
        cookies,
        target_origin="https://abc.services.example.net",
        port=8080,
        websocket=False,
    ) == tuple((name.decode(), value.decode()) for name, value in cookies[2:])
