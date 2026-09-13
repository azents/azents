"""Workspace model settings public API contract tests."""

import pytest
from pydantic import ValidationError

from .data import WorkspaceModelSettingsUpdateRequest


def test_workspace_settings_reject_removed_singular_model_fields() -> None:
    """Stale public v1 settings callers fail instead of losing model intent."""
    with pytest.raises(ValidationError):
        WorkspaceModelSettingsUpdateRequest.model_validate(
            {
                "default_model_selection": {
                    "llm_provider_integration_id": "integration-1",
                    "model_identifier": "model-1",
                }
            }
        )
