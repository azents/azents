"""Credential-free Brave Search product-path and image materialization E2E."""

import json

import azentsadminclient
import azentspublicclient
import boto3
import pytest
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from botocore.exceptions import ClientError
from testcontainers.core.container import DockerContainer

from support.utils import (
    single_candidate_model_options,
    unique,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    json_object_payload,
)
from tests.required.public.test_brave_search import _submit, _tool_events
from tests.required.public.test_per_prompt_inference_profile import (
    _create_profile_session,
)
from tests.required.public.test_provider_image_generation import (
    _wait_for_idle,
)
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
)

E2E_PLANNER_FALLBACK_WEIGHT = 10.0


def test_brave_storage_failure_cleans_partial_images_and_recovers(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
) -> None:
    """Deny model-file writes after Exchange uploads, then prove clean retry."""
    del azents_engine_worker_container, openai_proxy_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = auth_headers(workspace.token)
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="brave_search",
            slug="brave",
            name="Brave storage failure E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave storage failure E2E {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=False,
        ),
        _headers=headers,
    )
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    host = rustfs_container.get_container_host_ip()
    port = rustfs_container.get_exposed_port(9000)
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{host}:{port}",
        aws_access_key_id=rustfs_access_key,
        aws_secret_access_key=rustfs_secret_key,
        region_name="us-east-1",
    )
    workspace_id = toolkit.workspace_id
    denied_prefix = f"model-files/{workspace_id}/"
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyBraveModelFileUploadForE2E",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{s3_bucket_name}/{denied_prefix}*",
            }
        ],
    }

    def workspace_objects() -> list[str]:
        """List only this test's Exchange and ModelFile object prefixes."""
        keys: list[str] = []
        for prefix in (
            f"exchange/{workspace_id}/",
            denied_prefix,
        ):
            response = s3.list_objects_v2(Bucket=s3_bucket_name, Prefix=prefix)
            keys.extend(
                item["Key"]
                for item in response.get("Contents", [])
                if isinstance(item.get("Key"), str)
            )
        return keys

    applied = False
    try:
        s3.put_bucket_policy(Bucket=s3_bucket_name, Policy=json.dumps(policy))
        applied = True
        with pytest.raises(ClientError) as denied:
            s3.put_object(
                Bucket=s3_bucket_name,
                Key=f"{denied_prefix}policy-probe",
                Body=b"probe",
            )
        assert denied.value.response["Error"]["Code"] in {
            "AccessDenied",
            "Forbidden",
        }
        failed_session = _create_profile_session(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
        )
        _submit(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
            kind="images",
        )
        _wait_for_idle(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent.id,
            session_id=failed_session,
        )
        failed_events = _tool_events(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=failed_session,
        )
        assert any(
            json_object_payload(event.get("payload"), label="Failed Brave call").get(
                "name"
            )
            == "brave__search_images"
            for event in failed_events
            if event.get("kind") == "client_tool_call"
        )
        failed_results = [
            json_object_payload(event.get("payload"), label="Failed Brave result")
            for event in failed_events
            if event.get("kind") == "client_tool_result"
            and json_object_payload(
                event.get("payload"), label="Failed Brave result"
            ).get("name")
            == "brave__search_images"
        ]
        assert len(failed_results) == 1
        failed_result = failed_results[0]
        assert failed_result.get("status") == "failed"
        assert failed_result.get("output") == [
            {"type": "text", "text": "Generated image output could not be stored."}
        ]
        assert workspace_objects() == []
    finally:
        try:
            if applied:
                s3.delete_bucket_policy(Bucket=s3_bucket_name)
        finally:
            s3.close()

    recovered_session = _create_profile_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
    )
    _submit(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=recovered_session,
        kind="images",
    )
    _wait_for_idle(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent.id,
        session_id=recovered_session,
    )
    recovered = _tool_events(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=recovered_session,
    )
    results = [
        json_object_payload(event.get("payload"), label="Recovered Brave result")
        for event in recovered
        if event.get("kind") == "client_tool_result"
        and json_object_payload(
            event.get("payload"), label="Recovered Brave result"
        ).get("name")
        == "brave__search_images"
    ]
    assert len(results) == 1
    output = results[0].get("output")
    assert isinstance(output, list)
    attachments = [
        part
        for part in output
        if isinstance(part, dict) and part.get("type") == "attachment"
    ]
    assert len(attachments) == 2
