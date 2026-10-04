"""Pure canonical external-message Mailbox payload projection."""

from azents.core.enums import MailboxItemKind
from azents.core.external_channel_file import add_external_channel_file_locators
from azents.core.external_channel_labels import (
    ExternalChannelResourceLabels,
    decode_external_channel_reference_mappings,
    decode_external_channel_resource_labels,
)
from azents.engine.events.types import ExternalChannelMessagePayload
from azents.repos.external_channel.data import ExternalChannelMailboxProjectionItem
from azents.repos.mailbox.data import (
    ExternalChannelMessageMailboxPayload,
    MailboxPresentationItem,
)


def build_external_channel_mailbox_payload(
    item: ExternalChannelMailboxProjectionItem,
    *,
    context_omitted: bool,
    initial_title_eligible: bool,
) -> ExternalChannelMessageMailboxPayload:
    """Materialize one immutable External Channel message at admission."""
    if not item.provider_tenant_id:
        raise ValueError("External Channel message is missing provider tenant ID.")
    labels = decode_external_channel_resource_labels(item.resource_labels)
    references = decode_external_channel_reference_mappings(item.reference_mappings)
    payload = ExternalChannelMessagePayload(
        provider=item.provider,
        provider_tenant_id=item.provider_tenant_id,
        resource_id=item.resource_id,
        resource_label=_external_resource_label(
            labels, provider_resource_key=item.provider_resource_key
        ),
        resource_type=item.resource_type,
        binding_id=item.binding_id,
        invocation_batch_id=item.invocation_id,
        external_message_id=item.provider_message_key,
        projection_root_id=(
            f"external-channel:{item.binding_id}:{item.provider_message_key}"
        ),
        provider_message_key=item.provider_message_key,
        provider_position=item.provider_position,
        principal_id=item.principal_id,
        provider_user_id=item.provider_user_id,
        sender_display_name=item.sender_display_name,
        author_type=item.author_type,
        prompt_role=item.prompt_role,
        body=item.body,
        attachment_metadata=add_external_channel_file_locators(
            item.attachment_metadata or {},
            binding_id=item.binding_id,
            provider_message_key=item.provider_message_key,
        ),
        reference_mappings=references.to_payload(),
        provider_created_at=item.provider_created_at,
        provider_updated_at=item.provider_updated_at,
        original_url=item.original_url,
        truncated_context_message_count=0,
        truncated_context_size=0,
    )
    return ExternalChannelMessageMailboxPayload(
        type=MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE.value,
        items=[
            MailboxPresentationItem(
                item_key="external_channel_message:0",
                presentation_kind="external_channel_message",
                content=item.body or "",
                metadata={"external_channel_message": payload.model_dump(mode="json")},
            )
        ],
        context_omitted=context_omitted,
        initial_title_eligible=initial_title_eligible,
    )


def _external_resource_label(
    labels: ExternalChannelResourceLabels,
    *,
    provider_resource_key: str,
) -> str:
    """Return the validated provider resource label for one projection item."""
    if not labels.present:
        raise ValueError("External Channel message is missing resource labels.")
    channel_id = labels.channel_label
    if channel_id is None or not channel_id:
        raise ValueError("External Channel message is missing resource channel label.")
    thread_ts = labels.thread_label
    if labels.thread_label_invalid:
        raise ValueError("External Channel message has an invalid thread label.")
    if not isinstance(provider_resource_key, str) or not provider_resource_key:
        raise ValueError("External Channel message is missing resource identity.")
    return f"{channel_id}:{thread_ts}" if thread_ts else channel_id
