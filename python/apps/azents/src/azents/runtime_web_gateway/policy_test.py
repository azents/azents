"""Security-policy tests that prove rejection happens before proxying."""

import pytest

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.runtime_web_gateway.policy import (
    RuntimeWebPolicyCode,
    RuntimeWebPolicyError,
    evaluate_actual_origin,
    evaluate_preflight,
    normalize_request_headers,
    normalize_response_headers,
    parse_target_host,
    reject_service_worker_request,
    require_admitted_browser,
)
from azents.runtime_web_gateway.settings import RuntimeWebGatewayConfig

_CONFIG = RuntimeWebGatewayConfig(
    enabled=True,
    auth_mode=RuntimeWebAuthMode.SHARED_COOKIE,
    configuration_version=1,
    main_web_origin="https://app.example.com",
    broker_origin="https://auth.services.example.net",
    service_suffix="services.example.net",
    cookie_domain="services.example.net",
    identity_cookie_name="__Http-Azents-Runtime-Web",
    identity_lifetime_seconds=1_800,
    chromium_min_version=152,
    chromium_max_version=152,
    request_header_bytes=32 * 1024,
    request_body_bytes=64 * 1024 * 1024,
    frame_bytes=64 * 1024,
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


def test_service_worker_requests_are_rejected() -> None:
    for headers in (
        {"Sec-Fetch-Dest": "serviceworker"},
        {"Service-Worker": "script"},
    ):
        with pytest.raises(RuntimeWebPolicyError) as captured:
            reject_service_worker_request(headers)
        assert captured.value.code is RuntimeWebPolicyCode.FORBIDDEN


def test_browser_profile_requires_matching_protected_chromium_evidence() -> None:
    profile = require_admitted_browser(
        {
            "Sec-CH-UA": '"Not A Brand";v="99", "Chromium";v="152"',
            "User-Agent": "Mozilla/5.0 Chrome/152.0.0.0 Safari/537.36",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        },
        config=_CONFIG,
    )
    assert profile == "chromium-152"

    with pytest.raises(RuntimeWebPolicyError) as captured:
        require_admitted_browser(
            {
                "Sec-CH-UA": '"Chromium";v="152"',
                "User-Agent": "Mozilla/5.0 Chrome/153.0.0.0",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document",
            },
            config=_CONFIG,
        )
    assert captured.value.code is RuntimeWebPolicyCode.UPGRADE_REQUIRED


def test_preflight_and_actual_cors_require_an_admitted_source_origin() -> None:
    sources = frozenset(
        {
            "https://one.services.example.net",
            "https://two.services.example.net",
        }
    )
    preflight = evaluate_preflight(
        origin="https://one.services.example.net",
        requested_method="POST",
        requested_headers="Content-Type, Authorization",
        source_origins=sources,
    )
    actual = evaluate_actual_origin(
        origin="https://one.services.example.net",
        fetch_site="same-site",
        fetch_mode="cors",
        method="POST",
        target_origin="https://two.services.example.net",
        source_origins=sources,
    )

    assert ("Access-Control-Allow-Origin", preflight.origin) in preflight.headers
    assert ("Access-Control-Allow-Credentials", "true") in actual.headers

    with pytest.raises(RuntimeWebPolicyError):
        evaluate_preflight(
            origin="null",
            requested_method="POST",
            requested_headers=None,
            source_origins=sources,
        )


def test_header_normalization_strips_platform_authority_and_replaces_security() -> None:
    request_headers = normalize_request_headers(
        (
            (b"Cookie", b"__Http-Azents-Runtime-Web=secret; app=value"),
            (b"Authorization", b"Bearer application-token"),
            (b"Origin", b"https://abc.services.example.net"),
            (b"Connection", b"keep-alive"),
        ),
        port=8080,
        target_origin="https://abc.services.example.net",
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
        config=_CONFIG,
        cors=evaluate_actual_origin(
            origin=None,
            fetch_site="same-origin",
            fetch_mode="same-origin",
            method="GET",
            target_origin="https://abc.services.example.net",
            source_origins=frozenset(),
        ),
        target_origin="https://abc.services.example.net",
        port=8080,
    )

    assert (b"host", b"localhost:8080") in request_headers
    assert not any(name == b"cookie" for name, _value in request_headers)
    assert (b"authorization", b"Bearer application-token") in request_headers
    assert ("Set-Cookie", "app=value; Path=/") in response_headers
    assert (
        "Location",
        "https://abc.services.example.net/next?value=1",
    ) in response_headers
    assert ("Cache-Control", "no-store") in response_headers
    assert ("X-Frame-Options", "DENY") in response_headers
    assert not any(
        name == "Set-Cookie" and "__Http-Azents" in value
        for name, value in response_headers
    )
