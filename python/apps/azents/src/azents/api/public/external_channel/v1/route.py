"""External Channel v1 provider callback routes."""

import datetime
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse

from azents.services.external_channel.discord_http import (
    DiscordHTTPAdmissionService,
)
from azents.services.external_channel.discord_interaction import (
    MAX_DISCORD_INTERACTION_BODY_BYTES,
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
    discord_interaction_response_type,
)
from azents.services.external_channel.http_admission import SlackHTTPAdmissionService
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackHTTPInvalidPayload,
    SlackHTTPPayloadTooLarge,
    SlackHTTPUnauthorized,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/discord/interactions/{selector}", include_in_schema=False)
async def receive_discord_interaction(
    selector: str,
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[
        DiscordHTTPAdmissionService,
        Depends(DiscordHTTPAdmissionService),
    ],
    x_signature_ed25519: Annotated[
        str | None,
        Header(alias="X-Signature-Ed25519"),
    ] = None,
    x_signature_timestamp: Annotated[
        str | None,
        Header(alias="X-Signature-Timestamp"),
    ] = None,
) -> Response:
    """Authenticate one Discord interaction before acknowledging endpoint PING."""
    try:
        raw_body = await _read_bounded_discord_body(request)
        result = await service.handle(
            selector=selector,
            raw_body=raw_body,
            timestamp=x_signature_timestamp,
            signature=x_signature_ed25519,
            received_at=datetime.datetime.now(datetime.UTC),
        )
    except DiscordInteractionUnauthorized as error:
        logger.info(
            "Rejected unauthenticated Discord interaction",
            extra={"authentication_failure_code": error.failure_code},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Discord interaction could not be authenticated.",
        ) from error
    except DiscordInteractionInvalidPayload as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord interaction payload is invalid.",
        ) from error
    if result.ping:
        return JSONResponse(content={"type": 1})
    if result.response is not None:
        if result.control_plans:
            if result.control_delivery_connection_id is None:
                raise RuntimeError(
                    "Discord control deliveries require a connection identity."
                )
            for plan in result.control_plans:
                background_tasks.add_task(
                    service.attempt_control_delivery,
                    connection_id=result.control_delivery_connection_id,
                    plan=plan,
                )
        return JSONResponse(content=result.response)
    return JSONResponse(
        content={
            "type": discord_interaction_response_type(result.envelope.interaction_type)
        }
    )


@router.post("/slack/events", include_in_schema=False)
async def receive_slack_event(
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[SlackHTTPAdmissionService, Depends(SlackHTTPAdmissionService)],
    x_slack_request_timestamp: Annotated[
        str | None,
        Header(alias="X-Slack-Request-Timestamp"),
    ] = None,
    x_slack_signature: Annotated[
        str | None,
        Header(alias="X-Slack-Signature"),
    ] = None,
) -> Response:
    """Authenticate and durably admit one Slack Events API callback."""
    received_at = datetime.datetime.now(datetime.UTC)
    try:
        raw_body = await _read_bounded_body(request)
        result = await service.handle(
            raw_body=raw_body,
            timestamp_header=x_slack_request_timestamp,
            signature_header=x_slack_signature,
            received_at=received_at,
        )
    except SlackHTTPUnauthorized as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Slack callback could not be authenticated.",
        ) from error
    except SlackHTTPInvalidPayload as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slack callback payload is invalid.",
        ) from error
    except SlackHTTPPayloadTooLarge as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Slack callback payload exceeds the size limit.",
        ) from error
    if result.challenge is not None:
        return JSONResponse(content={"challenge": result.challenge})
    if result.interaction_handoff is not None:
        background_tasks.add_task(
            service.run_interaction_handoff,
            result.interaction_handoff,
        )
    if result.control_plans:
        if result.control_delivery_connection_id is None:
            raise RuntimeError(
                "Slack control deliveries require a connection identity."
            )
        for plan in result.control_plans:
            background_tasks.add_task(
                service.attempt_control_delivery,
                connection_id=result.control_delivery_connection_id,
                plan=plan,
            )
    return Response(status_code=status.HTTP_200_OK)


async def _read_bounded_body(request: Request) -> bytes:
    """Read an exact raw request body without buffering beyond the inbox limit."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise SlackHTTPInvalidPayload(
                "Slack callback Content-Length is invalid."
            ) from error
        if declared_length > MAX_SLACK_HTTP_BODY_BYTES:
            raise SlackHTTPPayloadTooLarge(
                "Slack callback payload exceeds the size limit."
            )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_SLACK_HTTP_BODY_BYTES:
            raise SlackHTTPPayloadTooLarge(
                "Slack callback payload exceeds the size limit."
            )
    return bytes(body)


async def _read_bounded_discord_body(request: Request) -> bytes:
    """Read one bounded Discord interaction body before signature verification."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise DiscordInteractionInvalidPayload(
                "Discord interaction Content-Length is invalid."
            ) from error
        if declared_length > MAX_DISCORD_INTERACTION_BODY_BYTES:
            raise DiscordInteractionInvalidPayload("Discord interaction is too large.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_DISCORD_INTERACTION_BODY_BYTES:
            raise DiscordInteractionInvalidPayload("Discord interaction is too large.")
    return bytes(body)
