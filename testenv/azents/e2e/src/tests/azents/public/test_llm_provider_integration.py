"""Public API LLM Provider Integration CRUD test.

LLM Provider Integrationt create/fetch/update/delete t verifyt.
"""

import uuid

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.aws_config import AwsConfig
from azentspublicclient.models.aws_secrets import AwsSecrets
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)
from azentspublicclient.models.gcp_config import GcpConfig
from azentspublicclient.models.gcp_secrets import GcpSecrets
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.llm_provider_integration_update_request import (
    LLMProviderIntegrationUpdateRequest,
)
from azentspublicclient.models.secrets import Secrets

from support.utils import authenticate_user, unique


def _setup_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> tuple[str, str]:
    """testt workspacet createt (access_token, handle)t return."""
    uniq = unique()
    access_token, _, _ = authenticate_user(public_api_client, admin_api_client)

    public_ws_api = PublicWorkspaceV1Api(public_api_client)
    handle = f"ws-llm-{uniq}"

    public_ws_api.workspace_v1_create_workspace(
        PublicCreateWorkspaceRequest(
            workspace_name=f"LLM Test {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers={"Authorization": f"Bearer {access_token}"},
    )

    return access_token, handle


class TestCreateIntegration:
    """LLM Provider Integration create test."""

    def test_create_openai_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """OpenAI integrationt createt configt Nonet."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="Test OpenAI",
                secrets=Secrets(ApiKeySecrets(api_key="sk-test-key-12345")),
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert created.id is not None
        assert created.provider == LLMProvider.OPENAI
        assert created.name == "Test OpenAI"
        assert created.config is None
        assert created.enabled is True
        assert created.created_at is not None
        assert created.updated_at is not None

    def test_create_aws_bedrock_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """AWS Bedrock integration create t configt returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.AWS_BEDROCK,
                name="Test AWS Bedrock",
                secrets=Secrets(
                    AwsSecrets(secret_access_key="wJalrXUtnFEMI/K7MDENG/test")
                ),
                config=LLMProviderIntegrationCreateRequestConfig(
                    AwsConfig(
                        access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
                    )
                ),
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert created.id is not None
        assert created.provider == LLMProvider.AWS_BEDROCK
        assert created.name == "Test AWS Bedrock"
        assert created.config is not None
        config = created.config.actual_instance
        assert config is not None
        assert isinstance(config, AwsConfig)
        assert config.access_key_id == "EXAMPLE_AWS_ACCESS_KEY_ID"
        assert config.region == "us-east-1"
        assert created.enabled is True

    def test_create_google_vertex_ai_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """Google Vertex AI integration create t configt returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.GOOGLE_VERTEX_AI,
                name="Test Vertex AI",
                secrets=Secrets(
                    GcpSecrets(
                        service_account_json='{"type":"service_account","project_id":"test"}'
                    )
                ),
                config=LLMProviderIntegrationCreateRequestConfig(
                    GcpConfig(project_id="my-gcp-project", region="us-central1")
                ),
            ),
            _headers={"Authorization": f"Bearer {access_token}"},
        )

        assert created.id is not None
        assert created.provider == LLMProvider.GOOGLE_VERTEX_AI
        assert created.name == "Test Vertex AI"
        assert created.config is not None
        config = created.config.actual_instance
        assert config is not None
        assert isinstance(config, GcpConfig)
        assert config.project_id == "my-gcp-project"
        assert config.region == "us-central1"
        assert created.enabled is True

    def test_create_integration_mismatched_credential_type_returns_422(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t t credential typet create t 422t returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)

        with pytest.raises(ApiException) as exc_info:
            api.llm_provider_integration_v1_create_integration(
                handle=handle,
                llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                    provider=LLMProvider.OPENAI,
                    secrets=Secrets(AwsSecrets(secret_access_key="wrong-type")),
                    config=LLMProviderIntegrationCreateRequestConfig(
                        AwsConfig(
                            access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID",
                            region="us-east-1",
                        )
                    ),
                ),
                _headers={"Authorization": f"Bearer {access_token}"},
            )
        assert exc_info.value.status == 422  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestListIntegrations:
    """LLM Provider Integration list fetch test."""

    def test_list_integrations(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t integrationt createt t list fetch t t t returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2t create
        api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="OpenAI 1",
                secrets=Secrets(ApiKeySecrets(api_key="sk-key-1")),
            ),
            _headers=headers,
        )
        api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.ANTHROPIC,
                name="Anthropic 1",
                secrets=Secrets(ApiKeySecrets(api_key="example-anthropic-api-key-1")),
            ),
            _headers=headers,
        )

        result = api.llm_provider_integration_v1_list_integrations(
            handle=handle,
            _headers=headers,
        )

        assert len(result.items) == 2
        names = {item.name for item in result.items}
        assert "OpenAI 1" in names
        assert "Anthropic 1" in names


class TestGetIntegration:
    """LLM Provider Integration t fetch test."""

    def test_get_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """createt integrationt IDt fetcht t fieldt existst."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.AWS_BEDROCK,
                name="Get Test Bedrock",
                secrets=Secrets(AwsSecrets(secret_access_key="wJalrXUtnFEMI/test")),
                config=LLMProviderIntegrationCreateRequestConfig(
                    AwsConfig(
                        access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID",
                        region="ap-northeast-2",
                    )
                ),
            ),
            _headers=headers,
        )

        fetched = api.llm_provider_integration_v1_get_integration(
            integration_id=created.id,
            handle=handle,
            _headers=headers,
        )

        assert fetched.id == created.id
        assert fetched.provider == LLMProvider.AWS_BEDROCK
        assert fetched.name == "Get Test Bedrock"
        assert fetched.enabled is True
        assert fetched.config is not None
        config = fetched.config.actual_instance
        assert isinstance(config, AwsConfig)
        assert config.access_key_id == "EXAMPLE_AWS_ACCESS_KEY_ID"
        assert config.region == "ap-northeast-2"
        assert fetched.created_at is not None
        assert fetched.updated_at is not None

    def test_get_nonexistent_integration_returns_404(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """existst t integration IDt fetch t 404t returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        nonexistent_id = str(uuid.uuid4())
        with pytest.raises(ApiException) as exc_info:
            api.llm_provider_integration_v1_get_integration(
                integration_id=nonexistent_id,
                handle=handle,
                _headers=headers,
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t


class TestUpdateIntegration:
    """LLM Provider Integration update test."""

    def test_update_name_only(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """t t t t."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="Original Name",
                secrets=Secrets(ApiKeySecrets(api_key="sk-test")),
            ),
            _headers=headers,
        )

        updated = api.llm_provider_integration_v1_update_integration(
            integration_id=created.id,
            handle=handle,
            llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
                name="Updated Name",
            ),
            _headers=headers,
        )

        assert updated.name == "Updated Name"
        assert updated.id == created.id

    def test_update_config_only(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """configt t t t (t: AWS region t)."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.AWS_BEDROCK,
                name="AWS Config Update",
                secrets=Secrets(AwsSecrets(secret_access_key="wJalrXUtnFEMI/test")),
                config=LLMProviderIntegrationCreateRequestConfig(
                    AwsConfig(
                        access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID", region="us-east-1"
                    )
                ),
            ),
            _headers=headers,
        )

        updated = api.llm_provider_integration_v1_update_integration(
            integration_id=created.id,
            handle=handle,
            llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
                config=LLMProviderIntegrationCreateRequestConfig(
                    AwsConfig(
                        access_key_id="EXAMPLE_AWS_ACCESS_KEY_ID",
                        region="ap-northeast-2",
                    )
                ),
            ),
            _headers=headers,
        )

        assert updated.config is not None
        config = updated.config.actual_instance
        assert isinstance(config, AwsConfig)
        assert config.region == "ap-northeast-2"
        assert config.access_key_id == "EXAMPLE_AWS_ACCESS_KEY_ID"

    def test_toggle_enabled(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """enabled statet t t t."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="Toggle Test",
                secrets=Secrets(ApiKeySecrets(api_key="sk-toggle-test")),
                enabled=True,
            ),
            _headers=headers,
        )
        assert created.enabled is True

        # inactivet
        disabled = api.llm_provider_integration_v1_update_integration(
            integration_id=created.id,
            handle=handle,
            llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
                enabled=False,
            ),
            _headers=headers,
        )
        assert disabled.enabled is False

        # t activet
        enabled = api.llm_provider_integration_v1_update_integration(
            integration_id=created.id,
            handle=handle,
            llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
                enabled=True,
            ),
            _headers=headers,
        )
        assert enabled.enabled is True


class TestDeleteIntegration:
    """LLM Provider Integration delete test."""

    def test_delete_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
    ) -> None:
        """integrationt deletet t fetch t 404t returnt."""
        access_token, handle = _setup_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        headers = {"Authorization": f"Bearer {access_token}"}

        created = api.llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="Delete Test",
                secrets=Secrets(ApiKeySecrets(api_key="sk-delete-test")),
            ),
            _headers=headers,
        )

        # delete
        api.llm_provider_integration_v1_delete_integration(
            integration_id=created.id,
            handle=handle,
            _headers=headers,
        )

        # delete t fetch t 404
        with pytest.raises(ApiException) as exc_info:
            api.llm_provider_integration_v1_get_integration(
                integration_id=created.id,
                handle=handle,
                _headers=headers,
            )
        assert exc_info.value.status == 404  # pyright: ignore[reportUnknownMemberType] # t create API clientt t t t
