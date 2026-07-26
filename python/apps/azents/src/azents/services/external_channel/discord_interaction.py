"""Bounded Discord HTTP interaction verification primitives."""

import datetime
import json
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from azents.core.enums import (
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.repos.external_channel.data import (
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)

MAX_DISCORD_INTERACTION_BODY_BYTES = 256 * 1024
DISCORD_INTERACTION_TTL = datetime.timedelta(minutes=15)


class DiscordInteractionError(ValueError):
    """Base class for controlled Discord interaction failures."""


class DiscordInteractionUnauthorized(DiscordInteractionError):
    """The interaction signature cannot be authenticated."""


class DiscordInteractionInvalidPayload(DiscordInteractionError):
    """The interaction payload is malformed or outside the supported boundary."""


@dataclass(frozen=True)
class DiscordInteractionEnvelope:
    """Minimal, capability-free facts needed to route one interaction."""

    interaction_id: str
    interaction_type: int
    application_id: str
    guild_id: str | None
    channel_id: str | None
    actor_user_id: str | None


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


def discord_interaction_admission_inputs(
    *,
    connection_id: str,
    envelope: DiscordInteractionEnvelope,
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
        or envelope.actor_user_id is None
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction is missing Guild routing or actor identity."
        )
    return DiscordInteractionAdmissionInputs(
        create=ExternalChannelInteractionCreate(
            connection_id=connection_id,
            transport=ExternalChannelTransport.HTTP,
            provider_interaction_key=envelope.interaction_id,
            interaction_type=interaction_type,
            callback_id=None,
            action_id=None,
            principal_id=None,
            resource_correlation_key=envelope.channel_id,
            projection={
                "interaction_type": interaction_type.value,
                "guild_id": envelope.guild_id,
                "channel_id": envelope.channel_id,
                "discord_interaction_type": str(envelope.interaction_type),
            },
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


def discord_interaction_response_type(interaction_type: int) -> int:
    """Return the provider acknowledgement type for an admitted interaction."""
    response_type = {
        2: 5,
        3: 6,
        4: 8,
        5: 5,
    }.get(interaction_type)
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
        raise DiscordInteractionUnauthorized("Discord signature headers are missing.")
    try:
        public_key_bytes = bytes.fromhex(public_key)
        signature_bytes = bytes.fromhex(signature)
        verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        verifier.verify(signature_bytes, timestamp.encode() + raw_body)
    except (ValueError, InvalidSignature) as error:
        raise DiscordInteractionUnauthorized(
            "Discord interaction signature is invalid."
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
    if not isinstance(payload, dict):
        raise DiscordInteractionInvalidPayload("Discord interaction must be an object.")
    interaction_id = payload.get("id")
    interaction_type = payload.get("type")
    application_id = payload.get("application_id")
    guild_id = payload.get("guild_id")
    channel_id = payload.get("channel_id")
    actor_user_id = _actor_user_id(payload)
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
    return DiscordInteractionEnvelope(
        interaction_id=interaction_id,
        interaction_type=interaction_type,
        application_id=application_id,
        guild_id=guild_id,
        channel_id=channel_id,
        actor_user_id=actor_user_id,
    )


def _actor_user_id(payload: dict[str, object]) -> str | None:
    """Extract an authenticated Discord actor without retaining profile content."""
    member = payload.get("member")
    if member is not None and not isinstance(member, dict):
        raise DiscordInteractionInvalidPayload("Discord interaction member is invalid.")
    member_user = member.get("user") if isinstance(member, dict) else None
    if member_user is not None and not isinstance(member_user, dict):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction member user is invalid."
        )
    member_user_id = member_user.get("id") if isinstance(member_user, dict) else None
    user = payload.get("user")
    if user is not None and not isinstance(user, dict):
        raise DiscordInteractionInvalidPayload("Discord interaction user is invalid.")
    user_id = user.get("id") if isinstance(user, dict) else None
    actor_user_id = member_user_id if member_user_id is not None else user_id
    if actor_user_id is not None and (
        not isinstance(actor_user_id, str) or not actor_user_id
    ):
        raise DiscordInteractionInvalidPayload(
            "Discord interaction actor identity is invalid."
        )
    return actor_user_id
