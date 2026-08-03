"""Model-visible External Channel provider reference mappings."""

from collections.abc import Mapping
from xml.sax.saxutils import quoteattr


def render_provider_reference_mappings(
    *,
    users: Mapping[str, str],
    channels: Mapping[str, str],
) -> tuple[str, ...]:
    """Render provider IDs and readable names as one concise XML appendix."""
    if not users and not channels:
        return ()
    lines = ["<provider_reference_mappings>"]
    lines.extend(
        "  <user "
        f"provider_id={quoteattr(_xml_text(identifier))} "
        "display_name="
        f"{quoteattr(_xml_text(_reference_display(display_name, prefix='@')))} />"
        for identifier, display_name in sorted(users.items())
    )
    lines.extend(
        "  <channel "
        f"provider_id={quoteattr(_xml_text(identifier))} "
        "display_name="
        f"{quoteattr(_xml_text(_reference_display(display_name, prefix='#')))} />"
        for identifier, display_name in sorted(channels.items())
    )
    lines.append("</provider_reference_mappings>")
    return tuple(lines)


def provider_reference_mappings_size(
    *,
    users: Mapping[str, str],
    channels: Mapping[str, str],
) -> int:
    """Return the UTF-8 size of the rendered provider-reference appendix."""
    lines = render_provider_reference_mappings(users=users, channels=channels)
    return len("\n".join(lines).encode())


def _reference_display(value: str, *, prefix: str) -> str:
    """Return one readable mapping value with its provider reference prefix."""
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _xml_text(value: str) -> str:
    """Remove characters that XML 1.0 cannot represent."""
    return "".join(
        character
        for character in value
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )
