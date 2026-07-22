"""External Channel v1 provider callback routes."""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from azents.services.external_channel.http_admission import SlackHTTPAdmissionService
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackHTTPInvalidPayload,
    SlackHTTPPayloadTooLarge,
    SlackHTTPUnauthorized,
)

router = APIRouter()


@router.post("/slack/events/{selector}", include_in_schema=False)
async def receive_slack_event(
    request: Request,
    service: Annotated[SlackHTTPAdmissionService, Depends(SlackHTTPAdmissionService)],
    selector: str,
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
    try:
        raw_body = await _read_bounded_body(request)
        result = await service.handle(
            selector=selector,
            raw_body=raw_body,
            timestamp_header=x_slack_request_timestamp,
            signature_header=x_slack_signature,
            received_at=datetime.datetime.now(datetime.UTC),
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
