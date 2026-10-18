"""Current Primary notification through real product HTTP and a local Slack fake."""

import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Literal

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.models.connection_access_policy_request import (
    ConnectionAccessPolicyRequest,
)
from azentspublicclient.models.external_channel_connection_status import (
    ExternalChannelConnectionStatus,
)
from azentspublicclient.models.external_channel_decision_input import (
    ExternalChannelDecisionInput,
)
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
from docker.models.containers import Container

from support import routine_model_fixture as model
from support.observations import ToolResultObservation
from support.utils import AgentSessionSetup, unique, wait_until
from tests.required.public.external_channel_scenarios import (
    _APP_ID,
    _BOT_TOKEN,
    _CHANNEL_ID,
    _SIGNING_SECRET,
    _TEAM_ID,
    _approval_request_id,
    _latest_setup_view,
    _open_slack_setup_modal,
    _provider_observation,
    _signed_headers,
    _submit_slack_setup_location,
)
from tests.required.public.test_routines import (
    RoutineChannelJourney,
    _write_evidence,
    run_routine_journey,
)
from tests.required.public.test_run_tool_to_file import _history, _live_idle


@pytest.mark.parametrize("delivery", ["delivered", "failed"])
def test_routine_current_primary_uses_one_provider_attempt_without_fallback(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    azents_engine_worker_container: Container,
    azents_external_channel_gateway_factory: Callable[
        [], AbstractContextManager[Container]
    ],
    slack_provider_fake_url: str,
    openai_proxy_url: str,
    delivery: Literal["delivered", "failed"],
) -> None:
    """Channel-created Session keeps Primary delivery separate from work outcome."""
    del azents_engine_worker_container
    gateway = azents_external_channel_gateway_factory()
    gateway.__enter__()
    request.addfinalizer(lambda: gateway.__exit__(None, None, None))
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset", timeout=10
    ).raise_for_status()

    def prepare(setup: AgentSessionSetup) -> str:
        headers = {"Authorization": f"Bearer {setup.access_token}"}
        api = ExternalChannelV1Api(public_api_client)
        connection = api.external_channel_v1_setup_slack_connection(
            agent_id=setup.agent_id,
            handle=setup.workspace_handle,
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
        ).connection
        request.addfinalizer(
            lambda: api.external_channel_v1_disconnect_connection(
                agent_id=setup.agent_id,
                handle=setup.workspace_handle,
                connection_id=connection.id,
                _headers=headers,
            )
        )

        def preserve_provider_evidence() -> None:
            state = _provider_observation(slack_provider_fake_url)
            _write_evidence(
                setup.session_id,
                "channel-observations",
                {
                    "request_counts": state.request_counts,
                    "deliveries": [
                        item.model_dump(mode="json") for item in state.deliveries
                    ],
                },
            )

        request.addfinalizer(preserve_provider_evidence)
        restricted = api.external_channel_v1_update_connection_access_policy(
            agent_id=setup.agent_id,
            handle=setup.workspace_handle,
            connection_id=connection.id,
            connection_access_policy_request=ConnectionAccessPolicyRequest(
                open_access_enabled=False
            ),
            _headers=headers,
        )
        assert restricted.open_access_enabled is False
        assert (
            api.external_channel_v1_validate_connection(
                agent_id=setup.agent_id,
                handle=setup.workspace_handle,
                connection_id=connection.id,
                _headers=headers,
            ).status
            is ExternalChannelConnectionStatus.ACTIVE
        )
        callback = f"{azents_public_server_url}/external-channel/v1/slack/events"
        timestamp = f"{int(time.time()) - 60}.000300"
        text = f"<@B-E2E> {model.CHANNEL_SETUP}"
        requests.post(
            f"{slack_provider_fake_url}/__testenv/configure",
            json={
                "history_pages": [
                    [{"user": "U-EXTERNAL", "ts": timestamp, "text": text}]
                ]
            },
            timeout=10,
        ).raise_for_status()
        body = json.dumps(
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
                    "user": "U-EXTERNAL",
                    "text": text,
                    "ts": timestamp,
                },
            },
            separators=(",", ":"),
        ).encode()
        requests.post(
            callback, data=body, headers=_signed_headers(body), timeout=10
        ).raise_for_status()
        approval_id = wait_until(
            lambda: _approval_request_id(slack_provider_fake_url),
            timeout=20,
            interval=0.2,
            message="Routine channel setup did not request participant approval",
        )
        assert approval_id is not None
        api.external_channel_v1_decide_approval_request(
            access_request_id=approval_id,
            external_channel_decision_input=ExternalChannelDecisionInput(
                decision="allow_agent", summary="Local Routine notification E2E"
            ),
            _headers=headers,
        )
        _open_slack_setup_modal(
            callback_url=callback,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            user_id="U-EXTERNAL",
        )
        view = wait_until(
            lambda: _latest_setup_view(slack_provider_fake_url),
            timeout=20,
            interval=0.2,
            message="Routine channel setup did not present the location selector",
        )
        assert view is not None
        _submit_slack_setup_location(
            callback_url=callback,
            app_id=_APP_ID,
            team_id=_TEAM_ID,
            user_id="U-EXTERNAL",
            setup_view=view,
        )
        chat = ChatV1Api(public_api_client)

        def bound_session() -> str | None:
            for session in chat.chat_v1_list_agent_sessions(
                agent_id=setup.agent_id, _headers=headers
            ).items:
                channels = api.external_channel_v1_list_session_channels(
                    agent_id=setup.agent_id,
                    handle=setup.workspace_handle,
                    session_id=session.id,
                    _headers=headers,
                )
                if len(channels.items) == 1:
                    return session.id
            return None

        session_id = wait_until(
            bound_session,
            timeout=30,
            interval=0.2,
            message="Routine channel setup did not create one bound Session",
        )
        assert session_id is not None
        common = {
            "server_url": azents_public_server_url,
            "token": setup.access_token,
            "session_id": session_id,
        }

        def setup_settled() -> bool:
            return _live_idle(**common) and any(
                item.kind == "client_tool_result"
                and ToolResultObservation.model_validate(
                    item.payload
                ).call_id.startswith("call_routine_e2e_channel_ignore_")
                and ToolResultObservation.model_validate(item.payload).status
                == "completed"
                for item in _history(**common).items
            )

        wait_until(
            setup_settled,
            timeout=60,
            interval=0.2,
            message="Channel setup Work did not finish through the actual ignore tool",
        )
        requests.post(
            f"{slack_provider_fake_url}/__testenv/configure",
            json={"delivery_scenarios": {"chat.postMessage": delivery}},
            timeout=10,
        ).raise_for_status()
        return session_id

    def verify(setup: AgentSessionSetup) -> None:
        state = _provider_observation(slack_provider_fake_url)
        assert state.request_counts.get("chat.postMessage") == 1
        notifications = [
            item for item in state.deliveries if item.operation == "chat.postMessage"
        ]
        if delivery == "delivered":
            assert len(notifications) == 1 and notifications[0].outcome == "delivered"
        else:
            assert notifications == []
        _write_evidence(
            setup.session_id,
            "primary-delivery",
            {
                "provider": "local_slack_fake",
                "post_attempt_count": state.request_counts["chat.postMessage"],
                "expected_delivery": delivery,
                "notifications": [
                    item.model_dump(mode="json") for item in notifications
                ],
            },
        )

    run_routine_journey(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_admin_server_url,
        openai_proxy_url,
        None,
        RoutineChannelJourney(prepare, verify, delivery),
    )
