"""One assembled issuer/configuration/authority/Proxy journey; no live providers."""

import hashlib
import json
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

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
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.selectable_model_settings_input import (
    SelectableModelSettingsInput,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from support.consts import REPOSITORY_ROOT
from support.llm_proxy_fixture import RESOLVER_KEY, ProxyFixture, write_tls_material
from support.utils import (
    AgentSetup,
    create_agent_setup,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)


class Issued(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    supply_id: str
    token_id: str
    agent_token: SecretStr = Field(repr=False)


@dataclass(frozen=True)
class Account:
    setup: AgentSetup = field(repr=False)
    selection: AgentModelSelectionInput
    key_hash: str

    def target(self, label: str) -> str:
        material = json.dumps(
            [
                label,
                self.selection.llm_provider_integration_id,
                self.selection.model_identifier,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()


@pytest.fixture
def llm_proxy_fixture(
    tmp_path: Path,
    azents_llm_proxy_image: str,
    container_network: Network,
    azents_public_server_container: DockerContainer,
) -> Iterator[ProxyFixture]:
    del azents_public_server_container
    container = (
        DockerContainer(azents_llm_proxy_image)
        .with_network(container_network)
        .with_exposed_ports(4000, 4443)
        .with_kwargs(entrypoint=["python", "/fixture/e2e_fixture.py"])
    )
    # The pytest fixture is Path-valued; no product state is written here.
    directory = tmp_path
    write_tls_material(directory, container.get_container_host_ip())
    shutil.copyfile(
        REPOSITORY_ROOT / "python/apps/azents-llm-proxy/scripts/e2e_fixture.py",
        directory / "e2e_fixture.py",
    )
    (directory / "e2e_fixture.py").chmod(0o644)
    container.with_volume_mapping(str(directory), "/fixture", "ro")
    for name, value in {
        "AZ_LLM_PROXY_AUTHORITY_URL": "https://localhost:4443/internal/llm",
        "AZ_LLM_PROXY_AUTHORITY_CA_FILE": "/fixture/certificate.pem",
        "AZ_LLM_PROXY_RESOLVER_KEY": RESOLVER_KEY,
        "AZ_FIXTURE_AUTHORITY_UPSTREAM": "http://azents-public-server:8010",
        "AZ_FIXTURE_CERT": "/fixture/certificate.pem",
        "AZ_FIXTURE_KEY": "/fixture/key.pem",
    }.items():
        container.with_env(name, value)
    container.start()
    host = container.get_container_host_ip()
    fixture = ProxyFixture(
        base_url=f"http://{host}:{container.get_exposed_port(4000)}",
        control_url=f"https://{host}:{container.get_exposed_port(4443)}",
        certificate=directory / "certificate.pem",
        container=container,
    )
    try:
        deadline = time.monotonic() + 45
        while True:
            try:
                health = requests.get(
                    fixture.base_url + "/health/liveliness", timeout=1
                )
                if health.status_code == 200:
                    fixture.journal()
                    break
            except requests.RequestException:
                pass
            if time.monotonic() >= deadline:
                stdout, stderr = container.get_logs()
                pytest.fail(
                    "Proxy E2E did not become ready.\n"
                    + stdout.decode()
                    + stderr.decode()
                )
            time.sleep(0.1)
        yield fixture
    finally:
        try:
            fixture.release()
        finally:
            container.stop()


def configure_account(
    public: azentspublicclient.ApiClient,
    admin: azentsadminclient.ApiClient,
    server_url: str,
    *,
    suffix: str,
    cap: int,
) -> Account:
    setup = create_agent_setup(public, admin, server_url)
    key = "sk-proxy-account-" + suffix + "-sentinel"
    headers = {"Authorization": "Bearer " + setup.access_token}
    integration = LLMProviderIntegrationV1Api(
        public
    ).llm_provider_integration_v1_create_integration(
        handle=setup.workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key=key)),
        ),
        _headers=headers,
    )
    selection = model_selection_from_first_candidate(
        server_url, setup.access_token, setup.workspace_handle, integration.id
    )
    account = Account(
        setup=setup,
        selection=selection,
        key_hash=hashlib.sha256(("Bearer " + key).encode()).hexdigest(),
    )
    configure_target(public, account, label="default", cap=cap)
    return account


def configure_target(
    public: azentspublicclient.ApiClient, account: Account, *, label: str, cap: int
) -> None:
    options = single_candidate_model_options(account.selection)
    options[0].label = label
    options[0].candidates[0].settings = SelectableModelSettingsInput(
        max_output_tokens=cap
    )
    AgentV1Api(public).agent_v1_update_agent(
        handle=account.setup.workspace_handle,
        agent_id=account.setup.agent_id,
        agent_update_request=AgentUpdateRequest(
            selectable_model_options=options,
            main_model_label=label,
            lightweight_model_label=label,
        ),
        _headers={"Authorization": "Bearer " + account.setup.access_token},
    )


def issue(admin: azentsadminclient.ApiClient, account: Account) -> Issued:
    token = admin.configuration.access_token
    assert token is not None
    response = requests.post(
        str(admin.configuration.host) + "/llm-access/v1/supplies",
        headers={"Authorization": "Bearer " + token},
        json={
            "agent_id": account.setup.agent_id,
            "supply_subject": "proxy-required-" + unique(),
        },
        timeout=10,
    )
    assert response.status_code == 201
    return Issued.model_validate_json(response.content)


def invoke(
    fixture: ProxyFixture,
    account: Account,
    issued: Issued,
    *,
    target: str,
    stream: bool = False,
) -> requests.Response:
    return requests.post(
        fixture.base_url + "/v1/responses",
        headers={"Authorization": "Bearer " + issued.agent_token.get_secret_value()},
        json={
            "model": account.selection.model_identifier,
            "metadata": {"azents_target_id": target},
            "input": "synthetic-assembled-private-prompt",
            "stream": stream,
        },
        stream=stream,
        timeout=(10, 30),
    )


def test_agent_inference_issuer_accounts_current_settings_and_admitted_stream(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    llm_proxy_fixture: ProxyFixture,
) -> None:
    fixture = llm_proxy_fixture
    a = configure_account(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        suffix="a",
        cap=64,
    )
    b = configure_account(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        suffix="b",
        cap=96,
    )
    assert a.selection.model_identifier == b.selection.model_identifier
    denied_issue = requests.post(
        str(admin_api_client.configuration.host) + "/llm-access/v1/supplies",
        headers={"Authorization": "Bearer " + a.setup.access_token},
        json={"agent_id": a.setup.agent_id, "supply_subject": "not-a-system-admin"},
        timeout=10,
    )
    assert denied_issue.status_code in {401, 403}
    issued_a, issued_b = issue(admin_api_client, a), issue(admin_api_client, b)
    listing = requests.get(
        fixture.base_url + "/v1/models",
        headers={"Authorization": "Bearer " + issued_a.agent_token.get_secret_value()},
        timeout=10,
    )
    listing.raise_for_status()
    assert a.selection.model_identifier in {
        item["id"] for item in listing.json()["data"]
    }
    assert invoke(fixture, a, issued_a, target=a.target("default")).status_code == 200
    assert invoke(fixture, b, issued_b, target=b.target("default")).status_code == 200
    assert invoke(fixture, a, issued_a, target=b.target("default")).status_code == 403
    assert len(fixture.journal()) == 2

    configure_target(public_api_client, a, label="replacement", cap=32)
    assert invoke(fixture, a, issued_a, target=a.target("default")).status_code == 403
    assert len(fixture.journal()) == 2
    response = invoke(fixture, a, issued_a, target=a.target("replacement"), stream=True)
    response.raise_for_status()
    lines = response.iter_lines(chunk_size=1)
    for line in lines:
        if b"admitted-stream-first-delta" in line:
            break
    else:
        pytest.fail("The admitted stream did not deliver its first delta.")
    admin_token = admin_api_client.configuration.access_token
    assert admin_token is not None
    revoked = requests.delete(
        str(admin_api_client.configuration.host)
        + f"/llm-access/v1/supplies/{issued_a.supply_id}/tokens/{issued_a.token_id}",
        headers={"Authorization": "Bearer " + admin_token},
        timeout=10,
    )
    assert revoked.status_code == 204
    assert (
        invoke(fixture, a, issued_a, target=a.target("replacement")).status_code == 401
    )
    assert len(fixture.journal()) == 3
    assert invoke(fixture, b, issued_b, target=b.target("default")).status_code == 200
    fixture.release()
    remaining = b"\n".join(lines)
    response.close()
    assert b"response.completed" in remaining and b"response.failed" not in remaining
    journal = fixture.journal()
    assert [
        (item.account_hash, item.max_output_tokens, item.streaming) for item in journal
    ] == [
        (a.key_hash, 64, False),
        (b.key_hash, 96, False),
        (a.key_hash, 32, True),
        (b.key_hash, 96, False),
    ]
    stdout, stderr = fixture.container.get_logs()
    logs = (stdout + stderr).decode()
    for sentinel in [
        issued_a.agent_token.get_secret_value(),
        issued_b.agent_token.get_secret_value(),
        "sk-proxy-account-a-sentinel",
        "sk-proxy-account-b-sentinel",
        "synthetic-assembled-private-prompt",
    ]:
        assert sentinel not in logs
    assert '"integration_id"' in logs and '"latency_ms"' in logs
