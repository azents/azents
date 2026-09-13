"""Public global account-link OAuth route contract tests."""

import datetime
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.enums import ExternalChannelProvider
from azents.core.external_account_link import (
    ExternalAccountLinkConflict,
    ExternalAccountLinkState,
    ExternalAccountLinkView,
)
from azents.services.external_account_link import ExternalAccountLinkService
from azents.services.external_account_oauth.link_service import (
    ExternalAccountOAuthService,
)
from azents.services.external_account_oauth_system_setting.data import (
    ExternalAccountOAuthDetail,
    ExternalAccountOAuthEffectiveStatus,
)
from azents.services.external_account_oauth_system_setting.service import (
    ExternalAccountOAuthSystemSettingService,
)

from .account_link_route import router

_NOW = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


class _LinkService:
    """Return one active global link for list and unlink tests."""

    async def list_links(self, **_: object) -> list[ExternalAccountLinkView]:
        return [
            ExternalAccountLinkView(
                id="link-1",
                workspace_id=None,
                workspace_name=None,
                workspace_handle=None,
                user_id="user-1",
                provider=ExternalChannelProvider.DISCORD,
                identity_scope="global",
                provider_user_id="123456789",
                provider_tenant_display_label=None,
                provider_display_label="Example User",
                linked_at=_NOW,
                state=ExternalAccountLinkState.ACTIVE,
            )
        ]

    async def unlink(self, **_: object) -> ExternalAccountLinkView:
        return (await self.list_links())[0]


class _OAuthService:
    """Return deterministic start/exchange outcomes."""

    conflict = False

    async def start(self, **_: object) -> object:
        return type(
            "StartResult", (), {"authorization_url": "https://provider.example"}
        )()

    async def exchange(self, **_: object) -> ExternalAccountLinkView:
        if self.conflict:
            raise ExternalAccountLinkConflict
        return (await _LinkService().list_links())[0]


class _SettingsService:
    """Return redacted provider availability details."""

    async def get_detail(self, provider: str) -> ExternalAccountOAuthDetail:
        return ExternalAccountOAuthDetail(
            section=f"{provider}_identity_oauth",
            provider=provider,
            schema_version=1,
            admin_version=1,
            effective_status=ExternalAccountOAuthEffectiveStatus.READY,
            callback_url=(
                f"https://azents.example/oauth/external-account/{provider}/callback"
            ),
            fields=(),
            health=None,
        )


def _client(
    oauth_service: _OAuthService | None = None,
) -> tuple[TestClient, _OAuthService]:
    service = oauth_service or _OAuthService()
    app = FastAPI()
    app.include_router(router, prefix="/external-channel/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-1",
        session_id="session-1",
        elevated=True,
    )
    app.dependency_overrides[ExternalAccountLinkService] = lambda: cast(
        Any,
        _LinkService(),
    )
    app.dependency_overrides[ExternalAccountOAuthService] = lambda: cast(
        Any,
        service,
    )
    app.dependency_overrides[ExternalAccountOAuthSystemSettingService] = lambda: cast(
        Any,
        _SettingsService(),
    )
    return TestClient(app), service


def test_global_list_omits_workspace_ownership_fields() -> None:
    """Global account responses never present a Workspace as link owner."""
    client, _ = _client()
    response = client.get("/external-channel/v1/account-links")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "link-1",
                "provider": "discord",
                "identity_scope": "global",
                "provider_user_id": "123456789",
                "provider_tenant_display_label": None,
                "provider_display_label": "Example User",
                "linked_at": "2026-09-13T00:00:00Z",
            }
        ]
    }


def test_oauth_start_and_exchange_are_authenticated_contracts() -> None:
    """Start returns a URL and exchange returns one global link projection."""
    client, _ = _client()

    start = client.post("/external-channel/v1/account-links/oauth/discord/start")
    exchange = client.post(
        "/external-channel/v1/account-links/oauth/discord/exchange",
        json={"code": "provider-code", "state": "state-value"},
    )

    assert start.status_code == 200
    assert start.headers["cache-control"] == "no-store"
    assert start.json() == {"authorization_url": "https://provider.example"}
    assert exchange.status_code == 200
    assert exchange.headers["cache-control"] == "no-store"
    assert "workspace_id" not in exchange.json()


def test_oauth_conflict_is_nondisclosing() -> None:
    """Conflict responses never disclose an existing owner's identity."""
    service = _OAuthService()
    service.conflict = True
    client, _ = _client(service)

    response = client.post(
        "/external-channel/v1/account-links/oauth/discord/exchange",
        json={"code": "provider-code", "state": "state-value"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "conflict",
            "message": "This external account cannot be connected.",
        }
    }


def test_legacy_origin_and_candidate_routes_are_deprecated_in_openapi() -> None:
    """Phase 2 keeps legacy clients compiling until Phase 3 removes the flow."""
    client, _ = _client()
    paths = cast(Any, client.app).openapi()["paths"]

    assert (
        paths["/external-channel/v1/account-link-origins/{origin_id}"]["get"][
            "deprecated"
        ]
        is True
    )
    assert (
        paths["/external-channel/v1/account-link-candidates/{candidate_id}"]["get"][
            "deprecated"
        ]
        is True
    )
    assert "/external-channel/v1/account-links/oauth/{provider}/start" in paths
