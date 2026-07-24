"""Tests for provider-neutral External Channel file contracts."""

import pytest
from pydantic import ValidationError

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import (
    ExternalChannelFileLocator,
    ExternalChannelFileMetadata,
    ExternalChannelFileUnsupportedReason,
    add_external_channel_file_locators,
    external_channel_file_metadata_items,
)


def test_file_metadata_requires_consistent_supported_state() -> None:
    """Supported entries require an ID and unsupported entries require a reason."""
    supported = ExternalChannelFileMetadata(
        provider=ExternalChannelProvider.SLACK,
        provider_file_id="F123",
        name="report.csv",
        title="Report",
        media_type="text/csv",
        declared_size=42,
        mode="hosted",
        external=False,
        file_access=None,
        supported=True,
        unsupported_reason=None,
    )
    assert supported.provider_file_id == "F123"

    with pytest.raises(ValidationError, match="requires an ID"):
        ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.SLACK,
            provider_file_id=None,
            name="report.csv",
            title=None,
            media_type=None,
            declared_size=None,
            mode="hosted",
            external=False,
            file_access=None,
            supported=True,
            unsupported_reason=None,
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.SLACK,
            provider_file_id="F123",
            name=None,
            title=None,
            media_type=None,
            declared_size=None,
            mode=None,
            external=False,
            file_access=None,
            supported=False,
            unsupported_reason=None,
        )


def test_file_locator_round_trips_escaped_components() -> None:
    """The plain versioned locator preserves provider-neutral component values."""
    locator = ExternalChannelFileLocator(
        provider=ExternalChannelProvider.SLACK,
        binding_id="binding:one",
        provider_file_id="file/one:two",
    )

    encoded = locator.encode()

    assert encoded == "external-file:v1:slack:binding%3Aone:file%2Fone%3Atwo"
    assert ExternalChannelFileLocator.parse(encoded) == locator


@pytest.mark.parametrize(
    "value",
    [
        "",
        "external-file:v2:slack:binding:file",
        "external-file:v1:unknown:binding:file",
        "external-file:v1:slack::file",
        "external-file:v1:slack:binding:",
    ],
)
def test_file_locator_rejects_malformed_values(value: str) -> None:
    """Unknown versions, providers, and blank identities fail closed."""
    with pytest.raises(ValueError):
        ExternalChannelFileLocator.parse(value)


def test_add_file_locators_returns_detached_enriched_metadata() -> None:
    """Invocation projection adds locators without mutating revision metadata."""
    metadata: dict[str, object] = {
        "files": [
            {
                "provider": "slack",
                "provider_file_id": "F123",
                "name": "report.csv",
                "supported": True,
                "unsupported_reason": None,
            },
            {
                "provider": "slack",
                "provider_file_id": None,
                "name": "malformed",
                "supported": False,
                "unsupported_reason": "missing_file_id",
            },
        ],
        "files_truncated": False,
    }

    enriched = add_external_channel_file_locators(
        metadata,
        binding_id="binding-1",
    )

    assert enriched is not metadata
    assert external_channel_file_metadata_items(enriched)[0]["file"] == (
        "external-file:v1:slack:binding-1:F123"
    )
    assert "file" not in external_channel_file_metadata_items(enriched)[1]
    assert "file" not in external_channel_file_metadata_items(metadata)[0]


def test_file_metadata_rejects_unbounded_text() -> None:
    """Provider text cannot bypass the shared bounded metadata contract."""
    with pytest.raises(ValidationError):
        ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.SLACK,
            provider_file_id="F123",
            name="x" * 256,
            title=None,
            media_type=None,
            declared_size=None,
            mode="hosted",
            external=False,
            file_access=None,
            supported=False,
            unsupported_reason=ExternalChannelFileUnsupportedReason.INVALID_SIZE,
        )
