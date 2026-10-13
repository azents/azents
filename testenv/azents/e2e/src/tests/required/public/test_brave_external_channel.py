"""Credential-free Brave Search product-path and image materialization E2E."""

import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from testcontainers.core.container import DockerContainer

from support.observations import ToolCallObservation, ToolResultObservation
from support.utils import (
    single_candidate_model_options,
    unique,
    wait_until,
)
from tests.required.public.external_channel_scenarios import (
    _APP_ID,
    _BOT_TOKEN,
    _CHANNEL_ID,
    _SIGNING_SECRET,
    _TEAM_ID,
    _latest_setup_view,
    _open_slack_setup_modal,
    _provider_state,
    _signed_headers,
    _submit_slack_setup_location,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
)
from tests.required.public.test_brave_search import _request_journal, _tool_events
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
)

E2E_PLANNER_FALLBACK_WEIGHT = 14.0


def test_brave_external_channel_reuses_one_search(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
    openai_proxy_url: str,
    slack_provider_fake_url: str,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[DockerContainer]
    ],
) -> None:
    """Publish search URLs through explicit Channel Action after one Brave call."""
    del azents_engine_worker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset", timeout=5
    ).raise_for_status()
    root_timestamp = f"{int(time.time()) - 60}.000103"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-BRAVE",
                        "ts": root_timestamp,
                        "text": "Brave Search E2E external_channel",
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()
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
            name="Brave Channel E2E",
            config={"country": "ALL", "search_lang": "en", "safesearch": "strict"},
            credentials={"api_key": "brave-e2e-valid"},
            enabled=True,
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Brave Channel E2E {unique()}",
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
    assert agent.runtime_capability == AgentRuntimeCapability.NONE
    ToolkitV1Api(public_api_client).toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    external_api = ExternalChannelV1Api(public_api_client)
    setup = external_api.external_channel_v1_setup_slack_connection(
        agent_id=agent.id,
        handle=workspace.handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_BOT_TOKEN,
                signing_secret=_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=headers,
    )
    request.addfinalizer(
        lambda: external_api.external_channel_v1_disconnect_connection(
            agent_id=agent.id,
            connection_id=setup.connection.id,
            handle=workspace.handle,
            _headers=headers,
        )
    )
    external_api.external_channel_v1_validate_connection(
        agent_id=agent.id,
        connection_id=setup.connection.id,
        handle=workspace.handle,
        _headers=headers,
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    with azents_external_channel_gateway_factory():
        channel_journal_start = len(_request_journal(openai_proxy_url))
        event_body = json.dumps(
            {
                "type": "event_callback",
                "event_id": f"Ev-{unique()}",
                "event_time": int(time.time()),
                "api_app_id": _APP_ID,
                "team_id": _TEAM_ID,
                "event": {
                    "type": "app_mention",
                    "channel": _CHANNEL_ID,
                    "channel_type": "channel",
                    "user": "U-BRAVE",
                    "text": "<@B-E2E> Brave Search E2E external_channel",
                    "ts": root_timestamp,
                },
            },
            separators=(",", ":"),
        ).encode()
        admitted = requests.post(
            callback_url,
            data=event_body,
            headers=_signed_headers(event_body),
            timeout=5,
        )
        assert admitted.status_code == 200
        _open_slack_setup_modal(
            callback_url=callback_url,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            user_id="U-BRAVE",
        )
        setup_view = wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=15,
            interval=0.2,
            message="Brave Channel setup view was not available",
        )
        assert setup_view is not None
        _submit_slack_setup_location(
            callback_url=callback_url,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            user_id="U-BRAVE",
            setup_view=setup_view,
        )
        chat_api = ChatV1Api(public_api_client)

        def bound_session() -> str | None:
            sessions = chat_api.chat_v1_list_agent_sessions(
                agent_id=agent.id, _headers=headers
            )
            for session in sessions.items:
                bindings = external_api.external_channel_v1_list_session_channels(
                    agent_id=agent.id,
                    session_id=session.id,
                    handle=workspace.handle,
                    _headers=headers,
                )
                if len(bindings.items) == 1 and bindings.items[0].work is not None:
                    return session.id
            return None

        session_id = wait_until(
            bound_session,
            timeout=30,
            interval=0.2,
            message="Brave Channel Session binding was not created",
        )
        assert session_id is not None

        def channel_result() -> list[ChatEventResponse] | None:
            events = _tool_events(
                server_url=azents_public_server_url,
                token=workspace.token,
                session_id=session_id,
            )
            matches = [
                event
                for event in events
                if event.kind == "client_tool_result"
                and ToolResultObservation.model_validate(event.payload).name
                == "channel_action"
            ]
            return events if len(matches) == 1 else None

        events = wait_until(
            channel_result,
            timeout=90,
            interval=0.2,
            message="Brave Channel publication did not complete",
        )
        assert events is not None
        calls = [
            ToolCallObservation.model_validate(event.payload)
            for event in events
            if event.kind == "client_tool_call"
        ]
        assert [call.name for call in calls] == [
            "brave__search_images",
            "channel_action",
        ]
        search_result = next(
            ToolResultObservation.model_validate(event.payload)
            for event in events
            if event.kind == "client_tool_result"
            and ToolResultObservation.model_validate(event.payload).name
            == "brave__search_images"
        )
        serialized = search_result.model_dump_json(exclude_unset=True)
        assert "https://example.org/brave/original-1.png" in serialized
        assert "https://example.org/brave/image-page-1" in serialized
        continuations = [
            model_request
            for model_request in _request_journal(openai_proxy_url)[
                channel_journal_start:
            ]
            if "call_brave_e2e_channel_images" in model_request.serialized()
            and "function_call_output" in model_request.serialized()
        ]
        assert any(
            "https://example.org/brave/original-1.png" in model_request.serialized()
            and "https://example.org/brave/image-page-1" in model_request.serialized()
            for model_request in continuations
        ), "Both URLs must reach the model before explicit Channel Action."
        channel_call = calls[1].model_dump_json(exclude_unset=True)
        assert "https://example.org/brave/original-1.png" in channel_call
        assert "https://example.org/brave/image-page-1" in channel_call
        finished = next(
            ToolResultObservation.model_validate(event.payload)
            for event in events
            if event.kind == "client_tool_result"
            and ToolResultObservation.model_validate(event.payload).name
            == "channel_action"
        )
        assert finished.status == "completed"
        output = finished.output
        assert isinstance(output, str)
        assert '"status": "delivered"' in output
        assert "brave-e2e-valid" not in json.dumps(
            [event.model_dump(mode="json", exclude_unset=True) for event in events]
        )
        delivery = _provider_state(slack_provider_fake_url)
        raw_deliveries = delivery.get("deliveries")
        assert isinstance(raw_deliveries, list)
        assert any(
            isinstance(item, dict)
            and item.get("operation") in {"chat.postMessage", "chat.update"}
            and item.get("outcome") == "delivered"
            for item in raw_deliveries
        )
