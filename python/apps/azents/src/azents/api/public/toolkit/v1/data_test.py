import pytest
from pydantic import TypeAdapter, ValidationError

from azents.api.public.toolkit.v1.data import (
    ToolkitConfigCreateRequest,
    ToolkitConfigUpdateRequest,
)


def test_toolkit_config_create_request_accepts_underscore_slug() -> None:
    request = ToolkitConfigCreateRequest(
        toolkit_type="kubernetes",
        slug="home_kubernetes",
        name="Home Kubernetes",
        config={},
    )

    assert request.slug == "home_kubernetes"


def test_toolkit_config_create_request_rejects_dash_slug() -> None:
    with pytest.raises(ValidationError):
        ToolkitConfigCreateRequest(
            toolkit_type="kubernetes",
            slug="home-kubernetes",
            name="Home Kubernetes",
            config={},
        )


def test_toolkit_config_update_request_accepts_underscore_slug() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    request = adapter.validate_python({"slug": "home_kubernetes"})

    assert request.get("slug") == "home_kubernetes"


def test_toolkit_config_update_request_rejects_dash_slug() -> None:
    adapter: TypeAdapter[ToolkitConfigUpdateRequest] = TypeAdapter(
        ToolkitConfigUpdateRequest
    )

    with pytest.raises(ValidationError):
        adapter.validate_python({"slug": "home-kubernetes"})
