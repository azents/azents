"""Tests for External Channel file-transfer System Settings contracts."""

import pytest
from pydantic import ValidationError

from azents.core.external_channel_file import (
    DEFAULT_EXTERNAL_CHANNEL_INBOUND_MAX_FILE_BYTES,
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES,
    DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES,
    MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES,
    MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES,
)
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
    ExternalChannelFilesSecrets,
    get_external_channel_files_definition,
)
from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingSection,
)


def test_external_channel_file_limits_use_provider_neutral_defaults() -> None:
    """The compiled policy defaults to 25 MiB files and 100 MiB actions."""
    config = ExternalChannelFilesConfig()

    assert (
        config.inbound_max_file_bytes == DEFAULT_EXTERNAL_CHANNEL_INBOUND_MAX_FILE_BYTES
    )
    assert (
        config.outbound_max_file_bytes
        == DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_FILE_BYTES
    )
    assert (
        config.outbound_max_action_bytes
        == DEFAULT_EXTERNAL_CHANNEL_OUTBOUND_MAX_ACTION_BYTES
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inbound_max_file_bytes", True),
        ("inbound_max_file_bytes", 0),
        ("inbound_max_file_bytes", MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES + 1),
        ("outbound_max_file_bytes", True),
        ("outbound_max_file_bytes", 0),
        ("outbound_max_file_bytes", MAX_EXTERNAL_CHANNEL_CONFIGURED_FILE_BYTES + 1),
        ("outbound_max_action_bytes", True),
        ("outbound_max_action_bytes", 0),
        (
            "outbound_max_action_bytes",
            MAX_EXTERNAL_CHANNEL_CONFIGURED_ACTION_BYTES + 1,
        ),
    ],
)
def test_external_channel_file_limits_are_positive_and_bounded(
    field: str,
    value: int | bool,
) -> None:
    """Administrator values cannot disable or unbound transfer enforcement."""
    with pytest.raises(ValidationError):
        ExternalChannelFilesConfig.model_validate({field: value})


def test_external_channel_action_limit_covers_one_outbound_file() -> None:
    """The aggregate action bound cannot be lower than the per-file bound."""
    with pytest.raises(ValidationError, match="must be at least"):
        ExternalChannelFilesConfig(
            inbound_max_file_bytes=1,
            outbound_max_file_bytes=2,
            outbound_max_action_bytes=1,
        )


def test_external_channel_files_definition_activates_directly() -> None:
    """The local provider-neutral policy needs no candidate validation workflow."""
    definition = get_external_channel_files_definition()

    assert definition.section is SystemSettingSection.EXTERNAL_CHANNEL_FILES
    assert definition.schema_version == 1
    assert definition.config_model is ExternalChannelFilesConfig
    assert definition.secret_model is ExternalChannelFilesSecrets
    assert definition.activation_mode is SystemSettingActivationMode.DIRECT
    assert definition.environment_bindings == ()
