"""Nominal provider identities through real API, worker and native SDK fixtures.

This small matrix shares one Runtime and creates fresh Sessions. Native bytes and
credential refresh are supplied by the real-process fixture composition, not by
this test or a canned application ModelResponse. Conditional protocol coverage
remains in unit/contract tests.
"""

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_update_request import AgentUpdateRequest
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.aws_config import AwsConfig
from azentspublicclient.models.aws_secrets import AwsSecrets
from azentspublicclient.models.gcp_config import GcpConfig
from azentspublicclient.models.gcp_secrets import GcpSecrets
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.selectable_model_settings_input import (
    SelectableModelSettingsInput,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from support.oauth_connections import (
    connect_chatgpt_oauth,
    connect_kimi_oauth,
    connect_xai_oauth,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import single_candidate_model_options, unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    create_agent,
    history_events,
    json_object,
    json_object_list_payload,
    json_object_payload,
    list_history,
    list_live,
    message_roles,
    run_message,
    setup_workspace,
    wait_for_rest_contents,
)

_FIXTURE_NAME = "__testenv_model_listing:deterministic-provider-core"
_CREDENTIAL_PREFIX = "e2e-provider-cutover-"
_CORE_REPLY = '{"title":"Provider cutover core"}'


@dataclass(frozen=True)
class _CoreCase:
    provider: LLMProvider
    model: str
    label: str


_CASES = (
    _CoreCase(LLMProvider.OPENAI, "gpt-5.5", "openai"),
    _CoreCase(LLMProvider.CHATGPT_OAUTH, "gpt-5.5", "chatgpt-oauth"),
    _CoreCase(LLMProvider.ANTHROPIC, "claude-sonnet-4-6", "anthropic"),
    _CoreCase(LLMProvider.GOOGLE_GEMINI, "gemini-2.5-pro", "gemini"),
    _CoreCase(LLMProvider.XAI, "grok-4", "xai-api-key"),
    _CoreCase(LLMProvider.XAI_OAUTH, "grok-4", "xai-oauth"),
    _CoreCase(LLMProvider.OPENROUTER, "anthropic/claude-sonnet-4.6", "openrouter"),
    _CoreCase(LLMProvider.KIMI_OAUTH, "kimi-k2.5", "kimi-oauth"),
    _CoreCase(LLMProvider.GOOGLE_VERTEX_AI, "gemini-2.5-pro", "vertex-google"),
    _CoreCase(
        LLMProvider.GOOGLE_VERTEX_AI,
        "publishers/anthropic/models/claude-sonnet-4-6",
        "vertex-anthropic",
    ),
    _CoreCase(
        LLMProvider.AWS_BEDROCK,
        "anthropic.claude-3-haiku-20240307-v1:0",
        "bedrock-anthropic",
    ),
    _CoreCase(LLMProvider.AWS_BEDROCK, "amazon.nova-lite-v1:0", "bedrock-amazon"),
    _CoreCase(
        LLMProvider.AWS_BEDROCK,
        "mistral.mistral-large-2407-v1:0",
        "bedrock-mistral",
    ),
)


@dataclass(frozen=True)
class _CoreSetup:
    token: str = field(repr=False)
    handle: str
    agent_id: str
    integrations: dict[LLMProvider, str]


def _service_account(token_uri: str) -> str:
    """Use real service-account signing/refresh with only synthetic key material."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "provider-cutover-core",
            "private_key_id": "provider-core-fixture-key",
            "private_key": private_key,
            "client_email": (
                "provider-cutover-core@provider-cutover-core.iam.gserviceaccount.com"
            ),
            "client_id": "123456789012345678901",
            "token_uri": token_uri,
        }
    )


def _create_integration(
    *,
    client: azentspublicclient.ApiClient,
    proxy_url: str,
    handle: str,
    token: str,
    provider: LLMProvider,
    service_account: str,
) -> str:
    """Create developer credentials or connect OAuth through supported public flow."""
    key = f"{_CREDENTIAL_PREFIX}{provider.value}-{unique()}"
    connections = {
        LLMProvider.CHATGPT_OAUTH: connect_chatgpt_oauth,
        LLMProvider.XAI_OAUTH: connect_xai_oauth,
        LLMProvider.KIMI_OAUTH: connect_kimi_oauth,
    }
    connect = connections.get(provider)
    if connect is not None:
        return connect(
            public_api_client=client,
            proxy_url=proxy_url,
            handle=handle,
            token=token,
            scenario=f"provider-core-{provider.value}-{unique()}",
            access_token=key,
            refresh_token=f"{_CREDENTIAL_PREFIX}refresh-{provider.value}-{unique()}",
            name=_FIXTURE_NAME,
            enabled=True,
        )
    if provider == LLMProvider.AWS_BEDROCK:
        secrets = Secrets(
            AwsSecrets(secret_access_key="synthetic-provider-core-secret")
        )
        config = LLMProviderIntegrationCreateRequestConfig(
            AwsConfig(
                access_key_id=key,
                region="us-east-1",
                role_arn="arn:aws:iam::123456789012:role/provider-core",
            )
        )
    elif provider == LLMProvider.GOOGLE_VERTEX_AI:
        secrets = Secrets(GcpSecrets(service_account_json=service_account))
        config = LLMProviderIntegrationCreateRequestConfig(
            GcpConfig(project_id="provider-cutover-core", region="us-central1")
        )
    else:
        secrets = Secrets(ApiKeySecrets(api_key=key))
        config = None
    return (
        LLMProviderIntegrationV1Api(client)
        .llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=provider,
                name=_FIXTURE_NAME,
                secrets=secrets,
                config=config,
            ),
            _headers=auth_headers(token),
        )
        .id
    )


def _wait_for_catalog_model(
    *, public_url: str, token: str, handle: str, integration_id: str, model: str
) -> None:
    """Wait for the current public catalog to authorize the exact selected raw ID."""

    def model_visible() -> bool:
        response = requests.get(
            f"{public_url}/llm-provider-integration/v1/workspaces/{handle}/"
            f"llm-provider-integrations/{integration_id}/catalog-entries",
            headers=auth_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        entries = json_object_list_payload(
            json_object(response).get("entries"), label="provider core catalog entries"
        )
        return any(
            entry.get("provider_model_identifier") == model
            and entry.get("visibility_status") == "selectable"
            for entry in entries
        )

    wait_until(model_visible, timeout=20, message=f"Native model missing: {model}")


@pytest.fixture(scope="session")
def provider_core_sdk_setup(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    openai_proxy_url: str,
    provider_core_cloud_token_url: str,
) -> _CoreSetup:
    """Own setup clients without depending on function-scoped client fixtures."""
    public_config = azentspublicclient.Configuration(host=azents_public_server_url)
    public_config.verify_ssl = False
    admin_config = azentsadminclient.Configuration(
        host=azents_admin_server_url,
        access_token=system_bootstrap_evidence.access_token,
    )
    admin_config.verify_ssl = False
    with (
        azentspublicclient.ApiClient(public_config) as public_client,
        azentsadminclient.ApiClient(admin_config) as admin_client,
    ):
        return _build_core_setup(
            public_api_client=public_client,
            admin_api_client=admin_client,
            azents_public_server_url=azents_public_server_url,
            openai_proxy_url=openai_proxy_url,
            provider_core_cloud_token_url=provider_core_cloud_token_url,
        )


def _build_core_setup(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    openai_proxy_url: str,
    provider_core_cloud_token_url: str,
) -> _CoreSetup:
    """Reuse one workspace and real Runtime, keeping parameterized failures separate."""
    workspace = setup_workspace(
        public_api_client, admin_api_client, azents_public_server_url
    )
    service_account = _service_account(provider_core_cloud_token_url)
    integrations: dict[LLMProvider, str] = {}
    for case in _CASES:
        if case.provider in integrations:
            continue
        integrations[case.provider] = _create_integration(
            client=public_api_client,
            proxy_url=openai_proxy_url,
            handle=workspace.handle,
            token=workspace.token,
            provider=case.provider,
            service_account=service_account,
        )
    _wait_for_catalog_model(
        public_url=azents_public_server_url,
        token=workspace.token,
        handle=workspace.handle,
        integration_id=integrations[LLMProvider.OPENAI],
        model="gpt-5.5",
    )
    selected_workspace = dataclasses.replace(
        workspace,
        model_selection=AgentModelSelectionInput(
            llm_provider_integration_id=integrations[LLMProvider.OPENAI],
            model_identifier="gpt-5.5",
        ),
    )
    return _CoreSetup(
        token=workspace.token,
        handle=workspace.handle,
        agent_id=create_agent(public_api_client, selected_workspace),
        integrations=integrations,
    )


def _wait_for_title(*, public_url: str, setup: _CoreSetup, session_id: str) -> None:
    """Observe the actual successful lightweight title operation, not a sleep."""

    def generated_title() -> bool:
        response = requests.get(
            f"{public_url}/chat/v1/agents/{setup.agent_id}/sessions/{session_id}",
            headers=auth_headers(setup.token),
            timeout=10,
        )
        response.raise_for_status()
        session = json_object(response)
        title = session.get("title")
        return (
            session.get("title_source") == "auto_generated"
            and isinstance(title, str)
            and "Provider cutover core" in title
        )

    wait_until(
        generated_title, timeout=15, message="Nominal native title was not generated"
    )


@pytest.mark.parametrize("case", _CASES, ids=[case.label for case in _CASES])
def test_provider_core_sdk_nominal_operations(
    case: _CoreCase,
    provider_core_sdk_setup: _CoreSetup,
    public_api_client: azentspublicclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Use selected native SDK through API admission and durable worker completion."""
    setup = provider_core_sdk_setup
    integration_id = setup.integrations[case.provider]
    _wait_for_catalog_model(
        public_url=azents_public_server_url,
        token=setup.token,
        handle=setup.handle,
        integration_id=integration_id,
        model=case.model,
    )
    selection = AgentModelSelectionInput(
        llm_provider_integration_id=integration_id, model_identifier=case.model
    )
    updated = AgentV1Api(public_api_client).agent_v1_update_agent(
        agent_id=setup.agent_id,
        handle=setup.handle,
        agent_update_request=AgentUpdateRequest(
            selectable_model_options=single_candidate_model_options(selection),
            main_model_label="default",
            lightweight_model_label="default",
        ),
        _headers=auth_headers(setup.token),
    )
    assert updated.main_model_label == "default"
    assert updated.lightweight_model_label == "default"
    session_response = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}/sessions",
        headers=auth_headers(setup.token),
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    session_response.raise_for_status()
    session_id = json_object(session_response).get("id")
    assert isinstance(session_id, str)
    prompt = f"Nominal native SDK smoke {case.label}"
    result = run_message(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=session_id,
        message=prompt,
    )
    assert result.session_id == session_id
    history = wait_for_rest_contents(
        server_url=azents_public_server_url,
        token=setup.token,
        session_id=session_id,
        expected=[prompt, _CORE_REPLY],
        timeout=25,
    )

    def run_is_idle() -> bool:
        live = list_live(
            server_url=azents_public_server_url,
            token=setup.token,
            session_id=session_id,
        )
        return live.get("run") is None and live.get("session_run_state") == "idle"

    wait_until(
        run_is_idle, timeout=15, message=f"Native Run did not settle: {case.label}"
    )
    history = list_history(
        server_url=azents_public_server_url,
        token=setup.token,
        session_id=session_id,
    )
    assert {"user", "assistant", "turn_complete"} <= set(message_roles(history))
    assistants = [
        event
        for event in history_events(history)
        if event.get("kind") == "assistant_message"
    ]
    assert assistants
    expected_adapter = (
        "openai"
        if case.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else "pydantic_ai"
    )
    for event in assistants:
        payload = json_object_payload(event.get("payload"), label="assistant payload")
        artifact = json_object_payload(
            payload.get("native_artifact"), label="persisted native identity"
        )
        assert artifact["provider"] == case.provider.value
        assert artifact["model"] == case.model
        assert artifact["adapter"] == expected_adapter
    _wait_for_title(
        public_url=azents_public_server_url, setup=setup, session_id=session_id
    )
    compact_response = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers=auth_headers(setup.token),
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"core-compact-{unique()}",
            "message": "",
            "action": {"type": "command", "name": "compact"},
            "inference_profile": None,
        },
        timeout=10,
    )
    compact_response.raise_for_status()

    def compacted() -> bool:
        payload = list_history(
            server_url=azents_public_server_url,
            token=setup.token,
            session_id=session_id,
        )
        return {"compaction_marker", "compaction_summary"} <= set(
            message_roles(payload)
        )

    wait_until(
        compacted,
        timeout=25,
        message=f"Nominal native compaction did not complete: {case.label}",
    )


def test_google_native_image_output_is_a_durable_downloadable_file(
    provider_core_sdk_setup: _CoreSetup,
    public_api_client: azentspublicclient.ApiClient,
    azents_public_server_url: str,
    azents_browser_s3_endpoint_url: str,
) -> None:
    """Materialize native image output without granting a public image builtin."""
    setup = provider_core_sdk_setup
    integration_id = setup.integrations[LLMProvider.GOOGLE_GEMINI]
    model = "gemini-3.1-flash-image-preview"
    _wait_for_catalog_model(
        public_url=azents_public_server_url,
        token=setup.token,
        handle=setup.handle,
        integration_id=integration_id,
        model=model,
    )
    selection = AgentModelSelectionInput(
        llm_provider_integration_id=integration_id, model_identifier=model
    )
    options = single_candidate_model_options(selection)
    options[0].candidates[0].settings = SelectableModelSettingsInput(builtin_tools=[])
    AgentV1Api(public_api_client).agent_v1_update_agent(
        agent_id=setup.agent_id,
        handle=setup.handle,
        agent_update_request=AgentUpdateRequest(
            selectable_model_options=options,
            main_model_label="default",
            lightweight_model_label="default",
        ),
        _headers=auth_headers(setup.token),
    )
    created = requests.post(
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}/sessions",
        headers=auth_headers(setup.token),
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    created.raise_for_status()
    session_id = json_object(created).get("id")
    assert isinstance(session_id, str)
    run_message(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=session_id,
        message="Draw a deterministic blue image with the selected hosted capability",
    )

    def completed() -> bool:
        live = list_live(
            server_url=azents_public_server_url,
            token=setup.token,
            session_id=session_id,
        )
        return live.get("run") is None and live.get("session_run_state") == "idle"

    wait_until(completed, timeout=25, message="Hosted image Run did not settle")
    history = list_history(
        server_url=azents_public_server_url, token=setup.token, session_id=session_id
    )
    images = []
    for event in history_events(history):
        if event.get("kind") != "provider_tool_call":
            continue
        payload = json_object_payload(event.get("payload"), label="hosted tool payload")
        if payload.get("name") == "image_generation":
            images.append(payload)
    assert len(images) == 1
    output = json_object_list_payload(
        json_object_payload(images[0].get("semantic"), label="image semantics").get(
            "output"
        ),
        label="durable image output",
    )
    image = next(part for part in output if part.get("type") == "file")
    assert image.get("kind") == "image"
    assert isinstance(image.get("model_file_id"), str)
    attachment = next(part for part in output if part.get("type") == "attachment")
    assert attachment.get("availability") == "available"
    assert attachment.get("media_type") == "image/png"
    attachment_id = attachment.get("attachment_id")
    assert isinstance(attachment_id, str)
    redirect = requests.get(
        f"{azents_public_server_url}/chat/v1/exchange-files/{attachment_id}/download",
        headers=auth_headers(setup.token),
        timeout=10,
        allow_redirects=False,
    )
    assert redirect.status_code == 302
    assert redirect.content == b""
    assert redirect.headers["Cache-Control"] == "no-store"
    assert redirect.headers["Referrer-Policy"] == "no-referrer"
    location = redirect.headers["Location"]
    assert urlsplit(location).scheme == "https"
    assert urlsplit(location).netloc == urlsplit(azents_browser_s3_endpoint_url).netloc
    try:
        # The observed local object-store gateway uses the suite's self-signed
        # TLS certificate. Follow only that fixture origin, without API tokens.
        downloaded = requests.get(location, timeout=10, verify=False)
    except requests.RequestException as error:
        raise AssertionError(
            f"Native image direct GET failed: {type(error).__name__}."
        ) from None
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert attachment.get("size") == len(downloaded.content)
    serialized = json.dumps(history)
    assert "inlineData" not in serialized
    assert "data:image" not in serialized
    artifact = json_object_payload(
        images[0].get("native_artifact"), label="hosted native artifact"
    )
    assert artifact.get("provider") == LLMProvider.GOOGLE_GEMINI.value
    assert artifact.get("model") == model
    supplemental = json_object_payload(
        json_object_payload(artifact.get("item"), label="native item").get(
            "supplement"
        ),
        label="native image provenance",
    )
    assert (
        supplemental.get("file_sha256")
        == hashlib.sha256(downloaded.content).hexdigest()
    )
