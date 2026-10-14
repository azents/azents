"""Strict shared wire codec for domain-specific Runtime stream authority."""

from datetime import UTC
from typing import assert_never

from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    StreamAuthority,
    WebStreamAuthority,
)


def encode_stream_authority(
    authority: StreamAuthority,
) -> runtime_stream_session_pb2.RuntimeStreamSessionAuthority:
    """Encode common transport identity and exactly one admitted domain."""
    message = runtime_stream_session_pb2.RuntimeStreamSessionAuthority(
        correlation_id=authority.correlation_id,
        authentication_session_id=authority.authentication_session_id,
        user_id=authority.user_id,
        agent_id=authority.agent_id,
        runtime_id=authority.runtime_id,
        desired_generation=authority.desired_generation,
        runner_generation=authority.runner_generation,
    )
    message.open_deadline_at.FromDatetime(authority.open_deadline_at)
    message.transport_deadline_at.FromDatetime(authority.transport_deadline_at)
    match authority:
        case WebStreamAuthority():
            message.web.CopyFrom(
                runtime_stream_session_pb2.RuntimeStreamSessionWebAuthority(
                    service_id=authority.service_id,
                    service_revision=authority.service_revision,
                    identity_id=authority.identity_id,
                    port=authority.port,
                )
            )
            message.web.exposure_deadline_at.FromDatetime(
                authority.exposure_deadline_at
            )
        case BrowserStreamAuthority():
            message.browser.CopyFrom(
                runtime_stream_session_pb2.RuntimeStreamSessionBrowserAuthority(
                    session_id=authority.session_id,
                    task_id=authority.task_id,
                    page_id=authority.page_id,
                    resource_incarnation=authority.resource_incarnation,
                    allow_input=authority.allow_input,
                )
            )
        case _:
            assert_never(authority)
    return message


def decode_stream_authority(
    message: runtime_stream_session_pb2.RuntimeStreamSessionAuthority,
) -> StreamAuthority:
    """Decode a complete domain variant; absent or unknown domains fail closed."""
    if not message.HasField("open_deadline_at") or not message.HasField(
        "transport_deadline_at"
    ):
        raise ValueError("Runtime stream authority deadlines are required")
    match message.WhichOneof("domain"):
        case "web":
            if not message.web.HasField("exposure_deadline_at"):
                raise ValueError("Runtime Web exposure deadline is required")
            return WebStreamAuthority(
                correlation_id=message.correlation_id,
                authentication_session_id=message.authentication_session_id,
                user_id=message.user_id,
                agent_id=message.agent_id,
                runtime_id=message.runtime_id,
                desired_generation=message.desired_generation,
                runner_generation=message.runner_generation,
                open_deadline_at=message.open_deadline_at.ToDatetime(tzinfo=UTC),
                transport_deadline_at=message.transport_deadline_at.ToDatetime(
                    tzinfo=UTC
                ),
                service_id=message.web.service_id,
                service_revision=message.web.service_revision,
                identity_id=message.web.identity_id,
                port=message.web.port,
                exposure_deadline_at=message.web.exposure_deadline_at.ToDatetime(
                    tzinfo=UTC
                ),
            )
        case "browser":
            return BrowserStreamAuthority(
                correlation_id=message.correlation_id,
                authentication_session_id=message.authentication_session_id,
                user_id=message.user_id,
                agent_id=message.agent_id,
                runtime_id=message.runtime_id,
                desired_generation=message.desired_generation,
                runner_generation=message.runner_generation,
                open_deadline_at=message.open_deadline_at.ToDatetime(tzinfo=UTC),
                transport_deadline_at=message.transport_deadline_at.ToDatetime(
                    tzinfo=UTC
                ),
                session_id=message.browser.session_id,
                task_id=message.browser.task_id,
                page_id=message.browser.page_id,
                resource_incarnation=message.browser.resource_incarnation,
                allow_input=message.browser.allow_input,
            )
        case _:
            raise ValueError("Runtime stream authority domain is required")
