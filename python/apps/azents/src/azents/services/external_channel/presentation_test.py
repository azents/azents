"""Slack current-Agent presentation tests."""

import datetime

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.services.external_channel.data import ExternalChannelCapabilitySnapshot
from azents.services.external_channel.presentation import (
    prepend_agent_blocks,
    prepend_agent_fallback,
    prepend_agent_markdown,
    resolve_slack_agent_presentation,
)
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)


def _target(
    *,
    agent_name: str,
    app_mode: ExternalChannelAppMode = ExternalChannelAppMode.MULTI,
    capabilities: dict[str, object] | None = None,
    agent_avatar: dict[str, object] | None = None,
) -> ChannelDeliveryTarget:
    return ChannelDeliveryTarget(
        delivery_attempt_id="delivery-1",
        operation=ExternalChannelDeliveryOperation.REPLY,
        status=ExternalChannelDeliveryStatus.PENDING,
        binding_id="binding-1",
        resource_id=None,
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        app_mode=app_mode,
        encrypted_credentials="ciphertext",
        provider_tenant_id="T-1",
        capabilities=capabilities,
        workspace_handle=None,
        agent_id=None,
        agent_session_id=None,
        agent_name=agent_name,
        agent_avatar=agent_avatar,
        request_payload={},
    )


def test_agent_name_is_bounded_escaped_and_shared_across_surfaces() -> None:
    """Visible Markdown and fallback text use one current canonical name."""
    presentation = resolve_slack_agent_presentation(
        _target(agent_name="  Agent <Ops> & Support  "),
        avatar_cdn_base_url=None,
    )

    assert presentation is not None
    assert presentation.name == "Agent <Ops> & Support"
    assert presentation.markdown_line == "*Agent &lt;Ops&gt; &amp; Support*"
    assert prepend_agent_markdown(presentation, "Answer") == (
        "*Agent &lt;Ops&gt; &amp; Support*\nAnswer"
    )
    assert prepend_agent_fallback(presentation, "Answer") == (
        "Agent <Ops> & Support\nAnswer"
    )
    assert prepend_agent_blocks(
        presentation,
        [{"type": "section", "text": {"type": "mrkdwn", "text": "Answer"}}],
    )[0] == {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Agent &lt;Ops&gt; &amp; Support*",
        },
    }


def test_single_app_omits_visible_agent_name_prefix() -> None:
    """A dedicated app identity does not repeat the Agent above each message."""
    presentation = resolve_slack_agent_presentation(
        _target(
            agent_name="Agent",
            app_mode=ExternalChannelAppMode.SINGLE,
        ),
        avatar_cdn_base_url=None,
    )

    assert presentation is not None
    assert prepend_agent_markdown(presentation, "Answer") == "Answer"
    assert prepend_agent_fallback(presentation, "Answer") == "Answer"
    blocks: list[dict[str, object]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "Answer"}}
    ]
    assert prepend_agent_blocks(presentation, blocks) == blocks


def test_icon_requires_capability_and_public_https_avatar() -> None:
    """Only validated customization scope and CDN content enable icon override."""
    capabilities = ExternalChannelCapabilitySnapshot(
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        inbound_events=True,
        thread_history=True,
        post_messages=True,
        update_messages=True,
        delete_messages=True,
        download_files=True,
        upload_files=True,
    ).model_dump(mode="json")
    capabilities["customize_messages"] = True
    avatar = StoredImage(
        filename="agent.png",
        default=StoredImageFile(
            key="avatars/agent/default.png",
            content_type="image/png",
            size_bytes=100,
            width=128,
            height=128,
        ),
        thumbnails=StoredImageThumbnails(
            medium=StoredImageFile(
                key="avatars/agent/medium image.png",
                content_type="image/png",
                size_bytes=80,
                width=96,
                height=96,
            )
        ),
        uploaded_at=datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC),
    )

    presentation = resolve_slack_agent_presentation(
        _target(
            agent_name="Agent",
            capabilities=capabilities,
            agent_avatar=avatar.model_dump(mode="json"),
        ),
        avatar_cdn_base_url="https://cdn.example/avatars",
    )
    insecure = resolve_slack_agent_presentation(
        _target(
            agent_name="Agent",
            capabilities=capabilities,
            agent_avatar=avatar.model_dump(mode="json"),
        ),
        avatar_cdn_base_url="http://private.example/avatars",
    )

    assert presentation is not None
    assert presentation.icon_url == (
        "https://cdn.example/avatars/avatars/agent/medium%20image.png"
    )
    assert insecure is not None
    assert insecure.icon_url is None


def test_legacy_capability_snapshot_uses_default_bot_icon() -> None:
    """Missing customization capability remains false for existing connections."""
    presentation = resolve_slack_agent_presentation(
        _target(
            agent_name="Agent",
            capabilities={
                "provider": "slack",
                "transport": "http",
                "inbound_events": True,
                "thread_history": True,
                "post_messages": True,
                "update_messages": True,
                "delete_messages": True,
                "download_files": True,
                "upload_files": True,
            },
            agent_avatar=None,
        ),
        avatar_cdn_base_url="https://cdn.example",
    )

    assert presentation is not None
    assert presentation.icon_url is None
