"""Personal management retains the production catalog and common Provider fields."""

import json
from unittest.mock import MagicMock

import pytest
from azcommon.result import Success

from azents.core.config import Config
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- common PostgreSQL fixture
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- exact account management fixture
)
from azents.services.toolkit.data import ToolkitConfigurationInput

_SERVICE_ACCOUNT = {
    "service_account_key": {
        "type": "service_account",
        "project_id": "fixture-project",
        "private_key": "fixture-private-key",
        "client_email": "fixture@example.test",
        "token_uri": "https://example.test/token",
    }
}
_INSTALLATIONS = [
    {
        "installation_id": "42",
        "account_login": "fixture",
        "account_type": "Organization",
        "account_avatar_url": None,
    }
]


@pytest.mark.parametrize(
    "toolkit_type,configuration,credentials",
    [
        ("mcp", {"server_url": "https://mcp.test", "auth_type": "none"}, None),
        (
            "mcp",
            {
                "server_url": "https://mcp.test",
                "auth_type": "header",
                "header_name": "X-Key",
            },
            {"type": "header", "value": "fixture-key"},
        ),
        (
            "mcp",
            {"server_url": "https://mcp.test", "auth_type": "bearer"},
            {"type": "bearer", "token": "fixture-token"},
        ),
        (
            "mcp",
            {
                "server_url": "https://mcp.test",
                "auth_type": "oauth2",
                "scopes": ["read", "write"],
            },
            {
                "type": "oauth2",
                "client_id": "fixture-client",
                "client_secret": "fixture-secret",
            },
        ),
        ("notion", {"timeout": 48}, None),
        ("sentry", {"timeout": 48, "enabled_skills": ["inspect"]}, None),
        (
            "gcp",
            {
                "project_id": "fixture-project",
                "services": ["logging", "gke"],
                "writable_services": ["gke"],
            },
            _SERVICE_ACCOUNT,
        ),
        (
            "aws",
            {
                "region": "ap-northeast-2",
                "role_arn": "fixture-role",
                "external_id": "fixture-external-id",
            },
            {"access_key_id": "AKIAFIXTURE", "secret_access_key": "fixture-secret"},
        ),
        (
            "google_analytics",
            {"default_property_id": "42", "timeout": 48},
            _SERVICE_ACCOUNT,
        ),
        (
            "brave_search",
            {"country": "KR", "search_lang": "ko", "safesearch": "off"},
            {"api_key": "fixture-key"},
        ),
        (
            "github",
            {
                "github_auth_type": "pat",
                "inject_runtime_environment": True,
                "toolsets": ["repos", "issues"],
            },
            {"type": "pat", "token": "fixture-token"},
        ),
        (
            "github",
            {"github_auth_type": "github_app", "inject_runtime_environment": True},
            {
                "type": "github_app",
                "app_id": "fixture-app",
                "private_key": "fixture-key",
                "installations": _INSTALLATIONS,
            },
        ),
        *[
            (
                "kubernetes",
                {
                    "clusters": [{"name": "fixture", "auth_type": auth_type}],
                    "read_only": False,
                    "allowed_namespaces": ["fixture"],
                    "denied_kinds": ["Secret", "RoleBinding"],
                },
                {"clusters": {"fixture": credential}},
            )
            for auth_type, credential in [
                ("token", {"type": "token", "token": "fixture-token"}),
                (
                    "kubeconfig",
                    {"type": "kubeconfig", "kubeconfig_yaml": "fixture-yaml"},
                ),
                (
                    "eks",
                    {
                        "type": "eks",
                        "aws_access_key_id": "fixture-key",
                        "aws_secret_access_key": "fixture-secret",
                    },
                ),
                (
                    "gke",
                    {
                        "type": "gke",
                        "service_account_key": _SERVICE_ACCOUNT["service_account_key"],
                    },
                ),
            ]
        ],
    ],
)
async def test_personal_uses_production_provider_validation_and_preserves_fields(
    harness: Harness,
    toolkit_type: str,
    configuration: dict[str, object],
    credentials: dict[str, object] | None,
) -> None:
    """Only external execution is omitted; real catalog/config/credential models run."""
    h = harness
    registry = get_toolkit_registry(
        repositories=MagicMock(),
        config=Config.model_construct(
            testenv_api_enabled=False, testenv_runtime_hook_qa_enabled=False
        ),
        artifact_service=MagicMock(),
        github_runtime=MagicMock(),
        github_user_runtime=MagicMock(),
        google_runtime=MagicMock(),
    )
    assert set(registry) == {
        "mcp",
        "github",
        "google",
        "notion",
        "sentry",
        "gcp",
        "aws",
        "google_analytics",
        "brave_search",
        "kubernetes",
    }
    h.common.toolkit_registry = registry
    request = ToolkitConfigurationInput(
        toolkit_type=toolkit_type,
        name="Personal fixture",
        slug="fixture",
        description="Shared fields",
        config=configuration,
        credentials=credentials,
        prompt="Common Provider guidance",
        enabled=True,
        always_expose_tools=True,
    )
    prepared = await h.common.prepare_configuration(request, user_id=h.subject.user_id)
    assert isinstance(prepared, Success)
    result = await h.service.create(h.subject, request)
    assert isinstance(result, Success)
    saved = result.value
    assert saved.config == prepared.value.configuration.config == configuration
    assert saved.credentials == prepared.value.configuration.credentials
    assert saved.description == request.description and saved.prompt == request.prompt
    assert saved.always_expose_tools
    if credentials is not None:
        assert saved.credentials is not None
        assert json.loads(saved.credentials) == credentials
    updated = await h.service.update(
        h.subject,
        saved.id,
        {"name": "Renamed", "config": configuration, "always_expose_tools": False},
    )
    assert isinstance(updated, Success)
    assert updated.value.id == saved.id and updated.value.name == "Renamed"
    assert updated.value.config == configuration
    assert updated.value.credentials == saved.credentials
    assert (
        updated.value.prompt == request.prompt and not updated.value.always_expose_tools
    )
