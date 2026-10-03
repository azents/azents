"""LLM integration and current catalog seeding helpers.

Normally use this through `TestenvClient.llm`.
"""

import time
from dataclasses import dataclass

from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.exceptions import NotFoundException
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.aws_config import AwsConfig
from azentspublicclient.models.aws_secrets import AwsSecrets
from azentspublicclient.models.llm_catalog_scope import LLMCatalogScope
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.secrets import Secrets

from testenv.runtime_config import TestenvConfig

from .client import public_client
from .types import Integration, User, Workspace
from .unique import unique

_INITIAL_CATALOG_TIMEOUT_SECONDS = 10.0
_INITIAL_CATALOG_POLL_SECONDS = 0.1


def _first_identifier(listing: ModelCatalogEntryListResponse, integration: Integration) -> str:
    """Read one exact typed candidate without a Workspace/default substitution."""
    if not listing.entries:
        raise RuntimeError(
            "The integration catalog has no selectable models. "
            "Complete catalog synchronization before creating the seed Agent."
        )
    candidate = listing.entries[0]
    if candidate.provider.value != integration.provider:
        raise RuntimeError("The current catalog model does not match the seed provider.")
    if not candidate.provider_model_identifier.strip():
        raise RuntimeError("The current catalog model identifier is blank.")
    return candidate.provider_model_identifier


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

        Testenv flows use current catalog listing and canonical model option inputs.
        Any scenario that still calls this helper should fail because it depends
        on the removed static catalog path.
        """
        _ = (slug, model_developer, provider)
        raise RuntimeError(
            "Static LLM catalog seeding is not supported. "
            "Create an integration and select a current model through public APIs instead."
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
    ) -> ModelCatalogEntryListResponse:
        """Read typed selectable current models through the generated public client."""
        api = LLMProviderIntegrationV1Api(public_client(self.config))
        return api.llm_provider_integration_v1_list_integration_catalog_entries(
            handle=workspace.handle,
            integration_id=integration.id,
            _headers={"Authorization": f"Bearer {user.access_token}"},
            _request_timeout=10,
        )

    def first_model_identifier(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
    ) -> str:
        """Return the exact first current candidate; never substitute a default model."""
        listing = self.list_integration_models(user, workspace, integration)
        return _first_identifier(listing, integration)

    def wait_for_initial_model_identifier(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
    ) -> str:
        """Wait for the newly created fixture's authoritative integration publication."""
        api = LLMProviderIntegrationV1Api(public_client(self.config))
        deadline = time.monotonic() + _INITIAL_CATALOG_TIMEOUT_SECONDS
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                listing = api.llm_provider_integration_v1_list_integration_catalog_entries(
                    handle=workspace.handle,
                    integration_id=integration.id,
                    _headers={"Authorization": f"Bearer {user.access_token}"},
                    _request_timeout=min(10.0, remaining),
                )
            except NotFoundException:
                pass
            else:
                if listing.catalog_scope is LLMCatalogScope.INTEGRATION:
                    sync = listing.latest_sync
                    if sync is not None:
                        match sync.status:
                            case "succeeded":
                                return _first_identifier(listing, integration)
                            case "failed":
                                raise RuntimeError(
                                    "Initial integration catalog synchronization failed."
                                )
                            case "running":
                                pass
                            case _:
                                raise ValueError("Unknown current catalog sync status.")
            if (remaining := deadline - time.monotonic()) > 0:
                time.sleep(min(_INITIAL_CATALOG_POLL_SECONDS, remaining))
        raise TimeoutError("Initial integration catalog publication did not become ready.")

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
