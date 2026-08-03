"""Tests for model-visible External Channel provider reference mappings."""

import xml.etree.ElementTree as ElementTree

from azents.core.external_channel_reference import (
    provider_reference_mappings_size,
    render_provider_reference_mappings,
)


def test_reference_mapping_is_valid_xml_with_untrusted_provider_text() -> None:
    """XML-invalid controls are removed while syntax characters remain escaped."""
    lines = render_provider_reference_mappings(
        users={'U&"1\x01': 'R&D "Ops"\x02'},
        channels={"C<1>": "alerts <prod>\x03"},
    )

    rendered = "\n".join(lines)
    mapping = ElementTree.fromstring(rendered)
    user = mapping.find("user")
    channel = mapping.find("channel")

    assert user is not None
    assert channel is not None
    assert user.attrib == {
        "provider_id": 'U&"1',
        "display_name": '@R&D "Ops"',
    }
    assert channel.attrib == {
        "provider_id": "C<1>",
        "display_name": "#alerts <prod>",
    }
    assert provider_reference_mappings_size(
        users={'U&"1\x01': 'R&D "Ops"\x02'},
        channels={"C<1>": "alerts <prod>\x03"},
    ) == len(rendered.encode())
