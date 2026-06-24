"""LLM integration and ModelConfig seeding helpers.

Normally use this through `TestenvClient.llm`.
"""

from dataclasses import dataclass

import httpx
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.aws_config import AwsConfig
from azentspublicclient.models.aws_secrets import AwsSecrets
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.secrets import Secrets

from testenv.runtime_config import TestenvConfig

from .client import public_client
from .types import Integration, User, Workspace
from .unique import unique


@dataclass(frozen=True)
class LLM:
    """LLM seed service used by `TestenvClient.llm`."""

    config: TestenvConfig

    def register_model(
        self,
        slug: str,
        *,
        model_developer: str = "openai",
        provider: str | None = None,
    ) -> None:
        """Block use of the legacy static catalog helper.

        Phase 5 testenv flows must use dynamic listing plus the ModelConfig API.
        Any scenario that still calls this helper should fail because it depends
        on the removed static catalog path.
        """
        _ = (slug, model_developer, provider)
        raise RuntimeError(
            "Static LLM catalog seeding is not supported. "
            "Create an integration and ModelConfig through public APIs instead."
        )

    def create_integration(
        self,
        user: User,
        workspace: Workspace,
        *,
        provider: str = "openai",
        api_key: str = "sk-test-dummy",
        name: str | None = None,
    ) -> Integration:
        """Call `POST /workspace/{handle}/llm-provider-integrations`.

        For ``provider="aws_bedrock"``, use ``create_bedrock_integration``
        instead because Bedrock uses AWS credentials. This helper is for
        `ApiKeySecrets` providers such as openai, anthropic, and google_gemini.
        """
        actual_name = name if name is not None else f"Test {provider} {unique()}"

        api = LLMProviderIntegrationV1Api(public_client(self.config))
        integration = api.llm_provider_integration_v1_create_integration(
            handle=workspace.handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider(provider),
                name=actual_name,
                secrets=Secrets(ApiKeySecrets(api_key=api_key)),
            ),
            _headers={"Authorization": f"Bearer {user.access_token}"},
        )

        return Integration(
            id=integration.id,
            workspace=workspace,
            provider=provider,
            name=actual_name,
        )

    def list_integration_models(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
    ) -> dict[str, object]:
        """Fetch integration-scoped dynamic model listing through the public API."""
        response = httpx.get(
            f"{self.config.public_url}/llm-provider-integration/v1/workspaces/"
            f"{workspace.handle}/llm-provider-integrations/{integration.id}/models",
            headers={"Authorization": f"Bearer {user.access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def create_model_config_from_first_candidate(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
        *,
        label: str | None = None,
        default_model: bool = True,
        default_lightweight_model: bool = True,
    ) -> str:
        """Create a ModelConfig from the first dynamic-listing candidate and return its ID."""
        listing = self.list_integration_models(user, workspace, integration)
        models = listing.get("models")
        if not isinstance(models, list) or not models:
            raise RuntimeError("Dynamic listing did not return usable models.")
        candidate = models[0]
        if not isinstance(candidate, dict):
            raise RuntimeError("Dynamic listing returned an invalid candidate.")
        response = httpx.post(
            f"{self.config.public_url}/model-config/v1/workspaces/{workspace.handle}/model-configs",
            headers={"Authorization": f"Bearer {user.access_token}"},
            json={
                "label": label if label is not None else f"Test Model {unique()}",
                "llm_provider_integration_id": integration.id,
                "provider": candidate["provider"],
                "model_identifier": candidate["model_identifier"],
                "default_model": default_model,
                "default_lightweight_model": default_lightweight_model,
                "enabled": True,
            },
            timeout=10,
        )
        response.raise_for_status()
        return str(response.json()["id"])

    def create_bedrock_integration(
        self,
        user: User,
        workspace: Workspace,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
        name: str | None = None,
    ) -> Integration:
        """Create an AWS Bedrock integration using `AwsConfig` and `AwsSecrets`.

        Bedrock uses AWS IAM credentials rather than API keys. The secret access
        key is stored in ``AwsSecrets.secret_access_key`` while access key id and
        region are saved in ``AwsConfig``.
        """
        actual_name = name if name is not None else f"Test Bedrock {unique()}"
        api = LLMProviderIntegrationV1Api(public_client(self.config))
        integration = api.llm_provider_integration_v1_create_integration(
            handle=workspace.handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider("aws_bedrock"),
                name=actual_name,
                secrets=Secrets(AwsSecrets(secret_access_key=secret_access_key)),
                config=LLMProviderIntegrationCreateRequestConfig(
                    AwsConfig(access_key_id=access_key_id, region=region),
                ),
            ),
            _headers={"Authorization": f"Bearer {user.access_token}"},
        )
        return Integration(
            id=integration.id,
            workspace=workspace,
            provider="aws_bedrock",
            name=actual_name,
        )
