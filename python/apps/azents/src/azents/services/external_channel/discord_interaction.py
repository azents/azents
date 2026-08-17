"""Bounded Discord HTTP interaction verification and typed admission primitives."""

import datetime
import json
from dataclasses import dataclass, field
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from azents.core.enums import (
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.core.external_channel_projection import is_external_channel_projection
from azents.repos.external_channel.data import (
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelTrigger,
)
from azents.repos.scheduled_task.data import MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH
from azents.services.external_channel.discord_api import (
    DiscordGuildCommandRole,
    DiscordGuildCommandSetCapability,
    discord_command_matches_capability,
    discord_command_role_from_name_and_type,
)
from azents.services.external_channel.discord_events import (
    project_discord_message_command_source_event,
)
from azents.services.scheduled_task.control import ScheduledTaskEditInput

MAX_DISCORD_INTERACTION_BODY_BYTES = 256 * 1024
DISCORD_INTERACTION_TTL = datetime.timedelta(minutes=15)
_DISCORD_MESSAGE_COMMAND_TYPE = 3
_DISCORD_THREAD_CHANNEL_TYPES = {10, 11, 12}


class DiscordInteractionError(ValueError):
    """Base class for controlled Discord interaction failures."""


DiscordInteractionAuthenticationFailureCode = Literal[
    "discord_callback_configuration_missing",
    "discord_callback_public_key_missing",
    "discord_interaction_signature_headers_missing",
    "discord_interaction_signature_invalid",
    "discord_interaction_application_mismatch",
    "discord_interaction_not_active",
    "discord_interaction_guild_mismatch",
]


class DiscordInteractionUnauthorized(DiscordInteractionError):
    """The interaction signature cannot be authenticated."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: DiscordInteractionAuthenticationFailureCode,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class DiscordInteractionInvalidPayload(DiscordInteractionError):
    """The interaction payload is malformed or outside the supported boundary."""


@dataclass(frozen=True)
class DiscordApplicationCommand:
    """Bounded application-command facts verified against current capability."""

    command_id: str
    name: str
    command_type: int


@dataclass(frozen=True)
class DiscordInteractionEnvelope:
    """Minimal, content-free facts needed to dispatch one authenticated interaction."""

    interaction_id: str
    interaction_type: int
    application_id: str
    guild_id: str | None
    channel_id: str | None
    provider_parent_channel_id: str | None
    provider_thread_id: str | None
    actor_user_id: str | None
    command: DiscordApplicationCommand | None
    message_command_source: dict[str, object] | None
    component_custom_id: str | None
    selected_value: str | None
    modal_custom_id: str | None
    scheduled_task_edit: ScheduledTaskEditInput | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True)
class DiscordInteractionAdmissionInputs:
    """Token-free canonical records projected from one verified interaction."""

    create: ExternalChannelInteractionCreate
    principal: ExternalChannelPrincipalCreate


def discord_interaction_type(
    interaction_type: int,
) -> ExternalChannelInteractionType | None:
    """Map supported Discord interaction categories to canonical callback types."""
    return {
        2: ExternalChannelInteractionType.SHORTCUT,
        3: ExternalChannelInteractionType.BLOCK_ACTION,
        4: ExternalChannelInteractionType.OPTIONS,
        5: ExternalChannelInteractionType.VIEW_SUBMISSION,
    }.get(interaction_type)


def validate_discord_command_capability(
    *,
    capabilities: dict[str, object] | None,
    envelope: DiscordInteractionEnvelope,
) -> DiscordGuildCommandRole | None:
    """Require every application command to match the current role capability proof."""
    command = envelope.command
    if command is None:
        return None
    raw_command_set = (
        None if capabilities is None else capabilities.get("discord_command_set")
    )
    try:
        command_set = DiscordGuildCommandSetCapability.model_validate(raw_command_set)
    except ValidationError as error:
        raise DiscordInteractionInvalidPayload(
            "Discord command capability is unavailable."
        ) from error
    role = discord_command_role_from_name_and_type(
        name=command.name,
        command_type=command.command_type,
    )
    if role is None or not discord_command_matches_capability(
        command_set=command_set,
        role=role,
        command_id=command.command_id,
        name=command.name,
        command_type=command.command_type,
    ):
        raise DiscordInteractionInvalidPayload("Discord command is not current.")
    return role


def discord_interaction_admission_inputs(
    *,
    connection_id: str,
    envelope: DiscordInteractionEnvelope,
    command_role: DiscordGuildCommandRole | None,
    received_at: datetime.datetime,
) -> DiscordInteractionAdmissionInputs:
    """Build bounded canonical admission inputs for one supported interaction."""
    interaction_type = discord_interaction_type(envelope.interaction_type)
    if interaction_type is None:
        raise DiscordInteractionInvalidPayload(
            "Discord interaction type is not supported."
        )
    if (
        envelope.guild_id is None
        or envelope.channel_id is None
        or envelope.provider_parent_channel_id is None
        or envelope.actor_user_id is None
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction is missing Guild routing or actor identity."
        )
    projection: dict[str, object] = {
        "interaction_type": interaction_type.value,
        "guild_id": envelope.guild_id,
        "channel_id": envelope.channel_id,
        "provider_parent_channel_id": envelope.provider_parent_channel_id,
        "discord_interaction_type": str(envelope.interaction_type),
    }
    if envelope.provider_thread_id is not None:
        projection["provider_thread_resource_key"] = (
            f"discord:{envelope.guild_id}:{envelope.provider_thread_id}"
        )
    if command_role is not None:
        projection["command_role"] = command_role.value
    if command_role is DiscordGuildCommandRole.MESSAGE_ACTION:
        projection["command_kind"] = "message_command"
    if envelope.message_command_source is not None:
        source_message_id = envelope.message_command_source.get("id")
        if isinstance(source_message_id, str) and source_message_id:
            projection["source_message_id"] = source_message_id
    return DiscordInteractionAdmissionInputs(
        create=ExternalChannelInteractionCreate(
            connection_id=connection_id,
            transport=ExternalChannelTransport.HTTP,
            provider_interaction_key=envelope.interaction_id,
            interaction_type=interaction_type,
            callback_id=None,
            action_id=None,
            principal_id=None,
            setup_claim_id=None,
            resource_correlation_key=envelope.channel_id,
            projection=projection,
            status=ExternalChannelInteractionStatus.ACCEPTED,
            expires_at=received_at + DISCORD_INTERACTION_TTL,
            error_kind=None,
            error_summary=None,
        ),
        principal=ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.DISCORD,
            provider_tenant_id=envelope.guild_id,
            provider_user_id=envelope.actor_user_id,
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )


def discord_message_command_source_event(
    *,
    connection_id: str,
    envelope: DiscordInteractionEnvelope,
    command_role: DiscordGuildCommandRole | None,
    received_at: datetime.datetime,
) -> ExternalChannelTrigger | None:
    """Build a safe source only for the capability-proven invocation command."""
    if (
        envelope.guild_id is None
        or envelope.message_command_source is None
        or command_role is not DiscordGuildCommandRole.MESSAGE_ACTION
    ):
        return None
    return project_discord_message_command_source_event(
        connection_id=connection_id,
        provider_app_id=envelope.application_id,
        provider_interaction_id=envelope.interaction_id,
        guild_id=envelope.guild_id,
        source_message=envelope.message_command_source,
        received_at=received_at,
    )


def discord_interaction_response_type(interaction_type: int) -> int:
    """Return the provider acknowledgement type for an admitted interaction."""
    response_type = {2: 5, 3: 6, 4: 8, 5: 5}.get(interaction_type)
    if response_type is None:
        raise DiscordInteractionInvalidPayload(
            "Discord interaction type is not supported."
        )
    return response_type


def verify_discord_interaction_signature(
    *,
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    public_key: str,
) -> None:
    """Verify the exact timestamp-prefixed raw body with an App public key."""
    if timestamp is None or signature is None:
        raise DiscordInteractionUnauthorized(
            "Discord signature headers are missing.",
            failure_code="discord_interaction_signature_headers_missing",
        )
    try:
        public_key_bytes = bytes.fromhex(public_key)
        signature_bytes = bytes.fromhex(signature)
        verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        verifier.verify(signature_bytes, timestamp.encode() + raw_body)
    except (ValueError, InvalidSignature) as error:
        raise DiscordInteractionUnauthorized(
            "Discord interaction signature is invalid.",
            failure_code="discord_interaction_signature_invalid",
        ) from error


def parse_discord_interaction(raw_body: bytes) -> DiscordInteractionEnvelope:
    """Parse one bounded interaction after signature verification."""
    if len(raw_body) > MAX_DISCORD_INTERACTION_BODY_BYTES:
        raise DiscordInteractionInvalidPayload("Discord interaction is too large.")
    try:
        payload: object = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiscordInteractionInvalidPayload(
            "Discord interaction is not valid JSON."
        ) from error
    if not is_external_channel_projection(payload):
        raise DiscordInteractionInvalidPayload("Discord interaction must be an object.")
    interaction_id = payload.get("id")
    interaction_type = payload.get("type")
    application_id = payload.get("application_id")
    guild_id = payload.get("guild_id")
    channel_id = payload.get("channel_id")
    if (
        not isinstance(interaction_id, str)
        or not interaction_id
        or not isinstance(interaction_type, int)
        or isinstance(interaction_type, bool)
        or not isinstance(application_id, str)
        or not application_id
        or guild_id is not None
        and not isinstance(guild_id, str)
        or channel_id is not None
        and not isinstance(channel_id, str)
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction has invalid routing fields."
        )
    provider_parent_channel_id, provider_thread_id = _channel_scope(
        payload=payload,
        channel_id=channel_id,
    )
    command = _application_command(payload=payload, interaction_type=interaction_type)
    message_command_source = _message_command_source(
        payload=payload,
        command=command,
        guild_id=guild_id,
        channel_id=channel_id,
        provider_parent_channel_id=provider_parent_channel_id,
        provider_thread_id=provider_thread_id,
    )
    component_custom_id, selected_value = _component(
        payload=payload,
        interaction_type=interaction_type,
    )
    modal_custom_id = _modal_custom_id(
        payload=payload,
        interaction_type=interaction_type,
    )
    scheduled_task_edit = _scheduled_task_edit(
        payload=payload,
        interaction_type=interaction_type,
        modal_custom_id=modal_custom_id,
    )
    return DiscordInteractionEnvelope(
        interaction_id=interaction_id,
        interaction_type=interaction_type,
        application_id=application_id,
        guild_id=guild_id,
        channel_id=channel_id,
        provider_parent_channel_id=provider_parent_channel_id,
        provider_thread_id=provider_thread_id,
        actor_user_id=_actor_user_id(payload),
        command=command,
        message_command_source=message_command_source,
        component_custom_id=component_custom_id,
        selected_value=selected_value,
        modal_custom_id=modal_custom_id,
        scheduled_task_edit=scheduled_task_edit,
    )


def _actor_user_id(payload: dict[str, object]) -> str | None:
    """Extract one authenticated Discord actor without retaining profile details."""
    member = payload.get("member")
    if member is not None and not is_external_channel_projection(member):
        raise DiscordInteractionInvalidPayload("Discord interaction member is invalid.")
    member_user = member.get("user") if is_external_channel_projection(member) else None
    if member_user is not None and not is_external_channel_projection(member_user):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction member user is invalid."
        )
    member_user_id = (
        member_user.get("id") if is_external_channel_projection(member_user) else None
    )
    user = payload.get("user")
    if user is not None and not is_external_channel_projection(user):
        raise DiscordInteractionInvalidPayload("Discord interaction user is invalid.")
    user_id = user.get("id") if is_external_channel_projection(user) else None
    actor_user_id = member_user_id if member_user_id is not None else user_id
    if actor_user_id is not None and (
        not isinstance(actor_user_id, str) or not actor_user_id
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction actor identity is invalid."
        )
    return actor_user_id


def _channel_scope(
    *,
    payload: dict[str, object],
    channel_id: str | None,
) -> tuple[str | None, str | None]:
    """Project the parent and thread identities without retaining a raw channel body."""
    if channel_id is None:
        return None, None
    channel = payload.get("channel")
    if channel is None:
        return None, None
    if not is_external_channel_projection(channel):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction channel is invalid."
        )
    projected_channel_id = channel.get("id")
    channel_type = channel.get("type")
    if (
        projected_channel_id != channel_id
        or not isinstance(channel_type, int)
        or isinstance(channel_type, bool)
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction channel is invalid."
        )
    if channel_type not in _DISCORD_THREAD_CHANNEL_TYPES:
        return channel_id, None
    parent_id = channel.get("parent_id")
    if not isinstance(parent_id, str) or not parent_id or parent_id == channel_id:
        raise DiscordInteractionInvalidPayload(
            "Discord interaction thread scope is invalid."
        )
    return parent_id, channel_id


def _application_command(
    *,
    payload: dict[str, object],
    interaction_type: int,
) -> DiscordApplicationCommand | None:
    """Extract exactly the bounded command fields authenticated by capability proof."""
    if interaction_type not in {2, 4}:
        return None
    data = payload.get("data")
    if not is_external_channel_projection(data):
        raise DiscordInteractionInvalidPayload(
            "Discord application command is invalid."
        )
    command_id = data.get("id")
    name = data.get("name")
    command_type = data.get("type")
    if (
        not isinstance(command_id, str)
        or not command_id.isdigit()
        or not isinstance(name, str)
        or not name
        or len(name) > 100
        or not isinstance(command_type, int)
        or isinstance(command_type, bool)
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord application command is invalid."
        )
    return DiscordApplicationCommand(
        command_id=command_id,
        name=name,
        command_type=command_type,
    )


def _message_command_source(
    *,
    payload: dict[str, object],
    command: DiscordApplicationCommand | None,
    guild_id: str | None,
    channel_id: str | None,
    provider_parent_channel_id: str | None,
    provider_thread_id: str | None,
) -> dict[str, object] | None:
    """Project one selected message only if the context command supplied it."""
    if command is None or command.command_type != _DISCORD_MESSAGE_COMMAND_TYPE:
        return None
    data = payload.get("data")
    if not is_external_channel_projection(data):
        return None
    target_id = data.get("target_id")
    resolved = data.get("resolved")
    if target_id is None and resolved is None:
        return None
    if (
        not isinstance(target_id, str)
        or not target_id
        or not is_external_channel_projection(resolved)
        or not isinstance(guild_id, str)
        or not guild_id
        or not isinstance(channel_id, str)
        or not channel_id
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord Message Command source is invalid."
        )
    messages = resolved.get("messages")
    source = (
        messages.get(target_id) if is_external_channel_projection(messages) else None
    )
    if not is_external_channel_projection(source):
        raise DiscordInteractionInvalidPayload(
            "Discord Message Command source is unavailable."
        )
    source_message = dict(source)
    source_message_id = source_message.get("id")
    source_channel_id = source_message.get("channel_id")
    if source_message_id != target_id or (
        source_channel_id is not None and source_channel_id != channel_id
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord Message Command source does not match its interaction."
        )
    source_message["id"] = target_id
    source_message["channel_id"] = channel_id
    if provider_thread_id is not None:
        source_message["thread"] = {
            "id": provider_thread_id,
            "parent_id": provider_parent_channel_id,
        }
    return source_message


def _component(
    *,
    payload: dict[str, object],
    interaction_type: int,
) -> tuple[str | None, str | None]:
    """Extract a compact component custom ID and at most one selected value."""
    if interaction_type != 3:
        return None, None
    data = payload.get("data")
    if not is_external_channel_projection(data):
        raise DiscordInteractionInvalidPayload("Discord component is invalid.")
    custom_id = data.get("custom_id")
    if not isinstance(custom_id, str) or not custom_id or len(custom_id) > 100:
        raise DiscordInteractionInvalidPayload("Discord component ID is invalid.")
    values = data.get("values")
    if values is None:
        return custom_id, None
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], str)
        or not values[0]
        or len(values[0]) > 64
    ):
        raise DiscordInteractionInvalidPayload("Discord component value is invalid.")
    return custom_id, values[0]


def _modal_custom_id(
    *,
    payload: dict[str, object],
    interaction_type: int,
) -> str | None:
    """Extract one bounded modal submission ID for explicit typed dispatch."""
    if interaction_type != 5:
        return None
    data = payload.get("data")
    if not is_external_channel_projection(data):
        raise DiscordInteractionInvalidPayload("Discord modal submission is invalid.")
    custom_id = data.get("custom_id")
    if not isinstance(custom_id, str) or not custom_id or len(custom_id) > 100:
        raise DiscordInteractionInvalidPayload("Discord modal submission is invalid.")
    return custom_id


def _scheduled_task_edit(
    *,
    payload: dict[str, object],
    interaction_type: int,
    modal_custom_id: str | None,
) -> ScheduledTaskEditInput | None:
    """Project exact bounded Scheduled Task edit fields from one known modal."""
    if interaction_type != 5 or modal_custom_id is None:
        return None
    if not modal_custom_id.startswith("st1:e:"):
        return None
    data = payload.get("data")
    components = (
        data.get("components") if is_external_channel_projection(data) else None
    )
    if not isinstance(components, list) or len(components) > 5:
        raise DiscordInteractionInvalidPayload(
            "Discord Scheduled Task edit is invalid."
        )
    values: dict[str, str | None] = {}
    for row in components:
        row_components = (
            row.get("components") if is_external_channel_projection(row) else None
        )
        if not isinstance(row_components, list) or len(row_components) != 1:
            raise DiscordInteractionInvalidPayload(
                "Discord Scheduled Task edit is invalid."
            )
        component = row_components[0]
        if not is_external_channel_projection(component):
            raise DiscordInteractionInvalidPayload(
                "Discord Scheduled Task edit is invalid."
            )
        custom_id = component.get("custom_id")
        value = component.get("value")
        if (
            not isinstance(custom_id, str)
            or custom_id
            not in {
                "azents_scheduled_task_title",
                "azents_scheduled_task_objective",
                "azents_scheduled_task_at",
                "azents_scheduled_task_cron",
                "azents_scheduled_task_timezone",
            }
            or not isinstance(value, str)
        ):
            raise DiscordInteractionInvalidPayload(
                "Discord Scheduled Task edit is invalid."
            )
        if custom_id in values:
            raise DiscordInteractionInvalidPayload(
                "Discord Scheduled Task edit is invalid."
            )
        limits = {
            "azents_scheduled_task_title": 120,
            "azents_scheduled_task_objective": MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
            "azents_scheduled_task_at": 128,
            "azents_scheduled_task_cron": 256,
            "azents_scheduled_task_timezone": 128,
        }
        if len(value) > limits[custom_id]:
            raise DiscordInteractionInvalidPayload(
                "Discord Scheduled Task edit is invalid."
            )
        values[custom_id] = value.strip() or None
    title = values.get("azents_scheduled_task_title")
    objective = values.get("azents_scheduled_task_objective")
    if not title or not objective or len(values) != 5:
        raise DiscordInteractionInvalidPayload(
            "Discord Scheduled Task edit is incomplete."
        )
    return ScheduledTaskEditInput(
        title=title,
        objective=objective,
        at=values["azents_scheduled_task_at"],
        cron=values["azents_scheduled_task_cron"],
        timezone=values["azents_scheduled_task_timezone"],
    )
