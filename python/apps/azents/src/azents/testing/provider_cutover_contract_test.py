"""Package-free application imports and generated public catalog contracts."""

import importlib.metadata
import importlib.util

import pytest

from azents.app import create_dummy_admin_app, create_dummy_public_app


def test_application_schemas_load_without_litellm_and_execution_descriptors() -> None:
    """Exercise actual route/schema composition, not AST-only absence checks."""
    assert importlib.util.find_spec("litellm") is None
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.distribution("litellm")
    public = create_dummy_public_app().openapi()
    admin = create_dummy_admin_app().openapi()
    assert public["paths"]
    assert admin["paths"]
    properties = public["components"]["schemas"]["ModelCatalogEntryResponse"][
        "properties"
    ]
    assert "provider_model_identifier" in properties
    assert "lowerer_target" not in properties
    assert "runtime_model_identifier" not in properties
