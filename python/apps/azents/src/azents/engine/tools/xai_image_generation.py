"""Auto-bound xAI Imagine image-generation client tool."""

import contextlib
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMProvider
from azents.engine.events.provider_output import generated_image_output
from azents.engine.run.errors import ModelCallError
from azents.engine.run.provider_failure import sanitize_provider_message
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.make_tool import make_tool
from azents.services.xai_imagine import (
    XaiImagineAuthenticationError,
    XaiImagineClient,
    XaiImagineError,
    XaiImaginePermissionError,
    XaiImagineRateLimitError,
    XaiImagineRequest,
    XaiImagineRequestError,
)

XaiImagineClientFactory = Callable[
    [], contextlib.AbstractAsyncContextManager[XaiImagineClient]
]
RefreshXaiAccessToken = Callable[[], Awaitable[str]]


class XaiImageGenerationInput(BaseModel):
    """Model-visible xAI image-generation arguments."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=1_024)
    aspect_ratio: Literal[
        "auto",
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
    ] = "auto"
    resolution: Literal["1k", "2k"] = "1k"


@dataclasses.dataclass(frozen=True)
class XaiImageGenerationExecutor:
    """Execute the semantic image-generation tool through xAI Imagine."""

    provider: LLMProvider
    access_token: str
    client_factory: XaiImagineClientFactory
    refresh_access_token: RefreshXaiAccessToken | None

    def make_tool(self) -> FunctionTool:
        """Build the unprefixed semantic image-generation function tool."""

        async def image_generation(
            arguments: XaiImageGenerationInput,
        ) -> FunctionToolResult:
            """Generate one image from a text prompt."""
            request = XaiImagineRequest(
                prompt=arguments.prompt,
                aspect_ratio=arguments.aspect_ratio,
                resolution=arguments.resolution,
            )
            encoded = await self._generate(request)
            try:
                generated = generated_image_output(encoded, output_index=0)
            except ModelCallError as exc:
                raise FunctionToolError(
                    "xAI Imagine returned an invalid generated image."
                ) from exc
            return FunctionToolResult(
                output=[],
                metadata={
                    "provider": "xai",
                    "operation": "image_generation",
                },
                generated_files=[generated],
            )

        return make_tool(
            image_generation,
            name="image_generation",
            description=(
                "Generate one image from a text prompt. Use aspect_ratio and "
                "resolution only for a requested composition or output size."
            ),
        )

    async def _generate(self, request: XaiImagineRequest) -> str:
        """Call Imagine and perform the one allowed OAuth authentication retry."""
        access_token = self.access_token
        refreshed = False
        async with self.client_factory() as client:
            while True:
                try:
                    return await client.generate(request, access_token=access_token)
                except XaiImagineAuthenticationError as exc:
                    if (
                        self.provider == LLMProvider.XAI_OAUTH
                        and self.refresh_access_token is not None
                        and not refreshed
                    ):
                        access_token = await self.refresh_access_token()
                        refreshed = True
                        continue
                    if refreshed:
                        raise FunctionToolError(
                            "xAI OAuth reconnect is required for image generation."
                        ) from exc
                    raise FunctionToolError(
                        "xAI Imagine rejected the integration credential."
                    ) from exc
                except XaiImaginePermissionError as exc:
                    raise FunctionToolError(
                        "xAI Imagine access is not permitted for this account."
                    ) from exc
                except XaiImagineRateLimitError as exc:
                    raise FunctionToolError(
                        "xAI Imagine rate limit was exceeded. Try again later."
                    ) from exc
                except XaiImagineRequestError as exc:
                    reason = sanitize_provider_message(exc.provider_message)
                    message = f"xAI Imagine returned HTTP {exc.status_code}."
                    if reason is not None:
                        message = (
                            f"xAI Imagine returned HTTP {exc.status_code}: {reason}"
                        )
                    raise FunctionToolError(
                        message,
                        metadata={
                            "provider": "xai",
                            "operation": "image_generation",
                            "code": "http_failure",
                            "status": exc.status_code,
                        },
                    ) from exc
                except XaiImagineError as exc:
                    raise FunctionToolError(str(exc)) from exc
