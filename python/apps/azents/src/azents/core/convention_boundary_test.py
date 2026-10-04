"""Focused behavior proofs for convention boundary corrections."""

import asyncio
from typing import Never
from unittest.mock import create_autospec

import httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from jinja2 import DictLoader, Environment
from pydantic import ValidationError
from slack_sdk.errors import SlackClientError
from slack_sdk.web.async_client import AsyncWebClient

from azents.core.config import (
    Config,
    Settings,
    WorkspaceS3Config,
    require_workspace_s3_bucket,
)
from azents.core.email.deps import get_template_environment
from azents.core.email.service import EmailService
from azents.core.engine_tool_state import McpToolSnapshotState
from azents.core.external_account_oauth import (
    DiscordIdentityOAuthAdapter,
    ExternalAccountOAuthProviderError,
    SlackIdentityOAuthAdapter,
)
from azents.core.external_channel_labels import (
    decode_external_channel_reference_mappings,
    decode_external_channel_resource_labels,
)
from azents.core.external_channel_mailbox_payload import _external_resource_label
from azents.core.external_channel_session_presence import (
    build_external_channel_session_url,
    session_presence_payload,
    setup_required_payload,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_projection import _effort_value
from azents.core.tools import TurnContext
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.wait import WaitToolkit
from azents.services.agent_wait import AgentWaitService
from azents.utils.appctx import AppContext


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        rdb_host="localhost",
        rdb_user="synthetic",
        rdb_db_name="synthetic",
        auth_jwt_secret_key="synthetic",
        credential_encryption_key="synthetic",
        web_url=None,
        api_url=None,
        oauth_secret_key=None,
        workspace_s3_bucket=None,
        external_channel_slack_callback_url=None,
        external_channel_discord_callback_url=None,
        broadcast_backend="redis",
    )


def test_configuration_absence_does_not_require_active_storage() -> None:
    settings = _settings()
    config = Config.from_settings(settings)
    assert config.web_url is None and config.api_url is None
    assert config.oauth_secret_key is None and config.workspace_s3.bucket is None
    assert config.external_channel_slack_callback_url is None
    assert config.external_channel_discord_callback_url is None
    dump = config.model_dump(mode="json")
    assert dump["web_url"] is None and dump["workspace_s3"]["bucket"] is None
    with pytest.raises(ValueError, match="not configured"):
        require_workspace_s3_bucket(config.workspace_s3)
    assert (
        require_workspace_s3_bucket(WorkspaceS3Config(bucket="explicit-bucket"))
        == "explicit-bucket"
    )
    explicit = Config.from_settings(settings.model_copy(update={"web_url": ""}))
    assert explicit.web_url == ""  # Explicit empty is distinct from omission.
    assert (
        build_external_channel_session_url(None, "workspace", "agent", "session")
        is None
    )


def test_broadcast_defaults_and_explicit_memory_selection_are_validated() -> None:
    assert Settings.model_fields["broadcast_backend"].default == "redis"
    assert Config.model_fields["broadcast_backend"].default == "redis"
    assert Config.from_settings(_settings()).broadcast_backend == "redis"
    selected = _settings().model_copy(update={"broadcast_backend": "memory"})
    assert Config.from_settings(selected).broadcast_backend == "memory"
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {**_settings().model_dump(), "broadcast_backend": "implicit-failover"}
        )


async def _publish(_event: object) -> None:
    return None


@pytest.mark.asyncio
async def test_unbound_turn_and_unloaded_snapshot_lifecycle_remain_explicit() -> None:
    context = TurnContext(
        workspace_id="workspace", model="model", run_id="run", publish_event=_publish
    )
    assert context.session_id is None
    state = McpToolSnapshotState()
    assert (
        state.server_url is None and state.tool_hash is None and state.loaded_at is None
    )
    assert state.model_dump(mode="json")["server_url"] is None
    assert McpToolSnapshotState.model_validate({}).server_url is None
    assert (
        McpToolSnapshotState.model_validate(
            {"server_url": "", "tool_hash": ""}
        ).server_url
        == ""
    )
    toolkit = WaitToolkit(wait_service=create_autospec(AgentWaitService, instance=True))
    assert "Use wait only" in await toolkit.get_static_prompt(context)
    with pytest.raises(FunctionToolError, match="AgentSession is unavailable"):
        await toolkit._wait(0)


@pytest.mark.asyncio
async def test_email_renderer_is_injected_and_cached_per_application_owner() -> None:
    env = Environment(
        loader=DictLoader({"synthetic": "Injected {{ value }}"}), autoescape=True
    )
    service = EmailService(config=None, ses_client=None, template_environment=env)
    assert (
        service._render_template("synthetic", value="<value>")
        == "Injected &lt;value&gt;"
    )
    config = Config.from_settings(_settings())
    async with AppContext(config) as first, AppContext(config) as second:
        one = await get_template_environment(first)
        assert await get_template_environment(first) is one
        assert await get_template_environment(second) is not one
        assert one.autoescape is True
        assert one.get_template("signup_token_en.txt") is one.get_template(
            "signup_token_en.txt"
        )


def test_closed_effort_dispatch_preserves_all_supported_values() -> None:
    assert [_effort_value(level) for level in ModelReasoningEffort] == [
        level.value for level in ModelReasoningEffort
    ]


@pytest.mark.parametrize("delivery", [None, "", 7, False, [], {}, "   ", "retained"])
def test_retained_delivery_decoder_does_not_validate_unrelated_label_fields(
    delivery: object,
) -> None:
    labels = {
        "provider": "discord",
        "delivery_channel_id": delivery,
        "thread_id": "root",
        "root_message_id": "root",
        "parent_channel_id": "parent",
        "guild_id": 123,
        "display_name": ["malformed unrelated"],
        "extension": {"opaque": 3},
    }
    decoded = decode_external_channel_resource_labels(labels)
    expected = delivery if isinstance(delivery, str) and delivery else None
    assert decoded.delivery_channel_id == expected
    payload = session_presence_payload(labels, state="joined")
    assert payload["channel_id"] == (expected or "root")
    assert payload["guild_id"] == 123  # Opaque coordinate relay remains unchanged.
    assert ("thread_parent_channel_id" in payload) is (delivery is None)


def test_reference_and_label_payload_presence_semantics() -> None:
    labels = decode_external_channel_resource_labels(
        {"channel_id": "channel", "thread_ts": ""}
    )
    assert (
        _external_resource_label(labels, provider_resource_key="resource") == "channel"
    )
    bad = decode_external_channel_resource_labels(
        {"channel_id": "channel", "thread_ts": 7}
    )
    with pytest.raises(ValueError, match="invalid thread label"):
        _external_resource_label(bad, provider_resource_key="resource")
    references = decode_external_channel_reference_mappings(
        {
            "users": {"one": "User", "": "blank", "invalid": 3},
            "channels": {"two": "Channel"},
            "extension": {"opaque": True},
        }
    )
    assert references.to_payload() == {
        "users": {"one": "User"},
        "channels": {"two": "Channel"},
    }
    assert decode_external_channel_reference_mappings(None).to_payload() == {}
    assert setup_required_payload(
        None, setup_claim_id="claim", claim_generation=1, source_revision=2
    ) == {
        "control_kind": "setup_required",
        "control_version": 2,
        "setup_claim_id": "claim",
        "claim_generation": 1,
        "source_revision": 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["slack", "discord"])
@pytest.mark.parametrize(
    "failure", [RuntimeError("programming defect"), asyncio.CancelledError()]
)
async def test_identity_adapters_propagate_unexpected_failures_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    failure: BaseException,
) -> None:
    async def fail(_client: object, *_args: object, **_kwargs: object) -> Never:
        raise failure

    adapter: SlackIdentityOAuthAdapter | DiscordIdentityOAuthAdapter
    if provider == "slack":
        monkeypatch.setattr(AsyncWebClient, "openid_connect_token", fail)
        adapter = SlackIdentityOAuthAdapter()
    else:
        monkeypatch.setattr(AsyncOAuth2Client, "fetch_token", fail)
        adapter = DiscordIdentityOAuthAdapter()
    with pytest.raises(type(failure)) as caught:
        await adapter.exchange_identity(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect_uri="uri",
            code_verifier=None,
        )
    assert caught.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["slack", "discord"])
async def test_expected_identity_provider_errors_remain_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    async def fail(_client: object, *_args: object, **_kwargs: object) -> Never:
        if provider == "slack":
            raise SlackClientError("sentinel-private-provider-content")
        raise httpx.ConnectError("sentinel-private-provider-content")

    adapter: SlackIdentityOAuthAdapter | DiscordIdentityOAuthAdapter
    if provider == "slack":
        monkeypatch.setattr(AsyncWebClient, "openid_connect_token", fail)
        adapter = SlackIdentityOAuthAdapter()
    else:
        monkeypatch.setattr(AsyncOAuth2Client, "fetch_token", fail)
        adapter = DiscordIdentityOAuthAdapter()
    with pytest.raises(ExternalAccountOAuthProviderError) as caught:
        await adapter.exchange_identity(
            client_id="client",
            client_secret="secret",
            code="code",
            redirect_uri="uri",
            code_verifier=None,
        )
    assert str(caught.value) == f"{provider}_identity_exchange_failed"
