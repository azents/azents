"""Disposable E2E entrypoint; never copied into or enabled by the product image.

Run from a read-only test fixture mount in the built Proxy image. The original
Proxy, authority client, guards, hooks and SDKs remain unchanged. Only final
provider HTTP is controlled. The TLS facade forwards authority traffic without
interpreting or replacing credentials/authorization. Fixture control is on a
separate TLS port, not the product's Agent ingress.
"""

import asyncio
import hashlib
import json
import os
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from pydantic import BaseModel, ConfigDict, Field

from azents_llm_proxy import application
from azents_llm_proxy.config import Settings
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.egress import NoReplayTransport, ProviderClients


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    model: str
    stream: bool = False
    input: object = Field(repr=False)
    max_output_tokens: int | None = None


class Observation(BaseModel):
    model: str
    account_hash: str
    max_output_tokens: int | None
    streaming: bool


@dataclass
class State:
    observations: list[Observation]
    release: asyncio.Event

    def provider(self, request: httpx.Request) -> httpx.Response:
        payload = ProviderRequest.model_validate_json(request.content)
        self.observations.append(
            Observation(
                model=payload.model,
                account_hash=hashlib.sha256(
                    request.headers["authorization"].encode()
                ).hexdigest(),
                max_output_tokens=payload.max_output_tokens,
                streaming=payload.stream,
            )
        )
        result = {
            "id": "resp_fixture",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "model": payload.model,
            "output": [],
            "parallel_tool_calls": True,
            "tools": [],
            "tool_choice": "auto",
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }
        if not payload.stream:
            return httpx.Response(200, json=result)
        return httpx.Response(
            200,
            stream=HeldStream(result, self.release),
            headers={"Content-Type": "text/event-stream"},
        )


class HeldStream(httpx.AsyncByteStream):
    def __init__(self, response: dict[str, object], release: asyncio.Event) -> None:
        self.response = response
        self.release = release

    @staticmethod
    def frame(event: dict[str, object]) -> bytes:
        return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.frame(
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**self.response, "status": "in_progress"},
            }
        )
        yield self.frame(
            {
                "type": "response.output_text.delta",
                "sequence_number": 1,
                "item_id": "msg_fixture",
                "output_index": 0,
                "content_index": 0,
                "delta": "admitted-stream-first-delta",
            }
        )
        await asyncio.wait_for(self.release.wait(), timeout=30)
        yield self.frame(
            {
                "type": "response.completed",
                "sequence_number": 2,
                "response": self.response,
            }
        )


async def main() -> None:
    state = State(observations=[], release=asyncio.Event())
    facade = FastAPI()
    upstream = os.environ["AZ_FIXTURE_AUTHORITY_UPSTREAM"]

    @facade.post("/internal/llm/{operation}")
    async def forward(operation: str, request: Request) -> Response:
        if operation not in {"resolve", "models"}:
            return Response(status_code=403)
        async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
            result = await client.post(
                f"{upstream}/internal/llm/{operation}",
                content=await request.body(),
                headers={
                    "Content-Type": "application/json",
                    "X-Azents-LLM-Resolver": request.headers.get(
                        "X-Azents-LLM-Resolver", ""
                    ),
                },
            )
        return Response(
            content=result.content,
            status_code=result.status_code,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @facade.get("/fixture/journal")
    async def journal() -> list[Observation]:
        return state.observations

    @facade.post("/fixture/release")
    async def release() -> Response:
        state.release.set()
        return Response(status_code=204)

    class FixtureClients(ProviderClients):
        @classmethod
        @asynccontextmanager
        async def open(cls, context: RequestContext) -> AsyncIterator[ProviderClients]:
            # Keep the product origin/no-replay guard before the controlled wire.
            handler = AsyncHTTPHandler(
                transport=NoReplayTransport(
                    httpx.MockTransport(state.provider), context.approve_egress
                ),
                follow_redirects=False,
            )
            try:
                yield cls(
                    handler=handler, tls=ssl.create_default_context(), context=context
                )
            finally:
                await handler.client.aclose()

    proxy = application.create_application(Settings(), provider_clients=FixtureClients)
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                facade,
                host="0.0.0.0",
                port=4443,
                ssl_certfile=os.environ["AZ_FIXTURE_CERT"],
                ssl_keyfile=os.environ["AZ_FIXTURE_KEY"],
                access_log=False,
            )
        ),
        uvicorn.Server(
            uvicorn.Config(proxy, host="0.0.0.0", port=4000, access_log=False)
        ),
    ]
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        state.release.set()
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
