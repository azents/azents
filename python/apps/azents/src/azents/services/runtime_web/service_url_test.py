"""Tests for Runtime Web service URL resolution."""

import pytest

from azents.services.runtime_web.service_url import (
    SettingsRuntimeWebServiceUrlResolver,
)


def test_resolves_stable_https_root_from_configured_suffix() -> None:
    resolver = SettingsRuntimeWebServiceUrlResolver(
        enabled=True,
        service_suffix="services.example.com",
    )

    assert (
        resolver.resolve("abcdefghijklmnopqrstuvwxyz234567")
        == "https://abcdefghijklmnopqrstuvwxyz234567.services.example.com/"
    )


@pytest.mark.parametrize(
    ("enabled", "service_suffix"),
    [(False, "services.example.com"), (True, None)],
)
def test_preserves_unconfigured_projection(
    enabled: bool,
    service_suffix: str | None,
) -> None:
    resolver = SettingsRuntimeWebServiceUrlResolver(
        enabled=enabled,
        service_suffix=service_suffix,
    )

    assert resolver.resolve("abcdefghijklmnopqrstuvwxyz234567") is None
