"""Auto-bound OpenAI Images API client tool."""

import dataclasses
from collections.abc import Awaitable, Callable

from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field

from azents.engine.events.openai_responses import OpenAIResponsesClientConfig
from azents.engine.events.provider_output import generated_image_output
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.make_tool import make_tool

OPENAI_IMAGE_DEFAULT_MODEL = "gpt-image-2"
OpenAIImagesClientFactory = Callable[[], AsyncOpenAI]
RefreshOpenAICredential = Callable[[], Awaitable[None]]


class OpenAIImageGenerationInput(BaseModel):
    """Model-visible image generation arguments."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=32_000)


@dataclasses.dataclass(frozen=True)
class OpenAIImageGenerationExecutor:
    """Generate one image through the selected OpenAI integration."""

    model_identifier: str
    client_factory: OpenAIImagesClientFactory
    refresh_credential: RefreshOpenAICredential | None

    def make_tool(self) -> FunctionTool:
        """Build the unprefixed semantic image-generation function tool."""

        async def image_generation(
            arguments: OpenAIImageGenerationInput,
        ) -> FunctionToolResult:
            """Generate one image from a text prompt."""
            refreshed = False
            while True:
                try:
                    async with self.client_factory() as client:
                        response = await client.images.generate(
                            model=self.model_identifier,
                            prompt=arguments.prompt,
                            n=1,
                        )
                except AuthenticationError as exc:
                    if self.refresh_credential is not None and not refreshed:
                        await self.refresh_credential()
                        refreshed = True
                        continue
                    message = (
                        "ChatGPT OAuth reconnect is required for image generation."
                        if refreshed
                        else "OpenAI image generation requires a valid "
                        "integration credential."
                    )
                    raise FunctionToolError(message) from exc
                except PermissionDeniedError as exc:
                    raise FunctionToolError(
                        "OpenAI image generation is not permitted for this account."
                    ) from exc
                except RateLimitError as exc:
                    raise FunctionToolError(
                        "OpenAI image generation rate limit was exceeded. "
                        "Try again later."
                    ) from exc
                except APIStatusError as exc:
                    raise FunctionToolError(
                        f"OpenAI image generation returned HTTP {exc.status_code}.",
                        metadata={
                            "provider": "openai",
                            "operation": "image_generation",
                            "code": "http_failure",
                            "status": exc.status_code,
                        },
                    ) from exc
                except APIConnectionError as exc:
                    raise FunctionToolError(
                        "OpenAI image generation could not reach the provider."
                    ) from exc
                except OpenAIError as exc:
                    raise FunctionToolError("OpenAI image generation failed.") from exc
                break

            encoded = response.data[0].b64_json if response.data else None
            if not encoded:
                raise FunctionToolError(
                    "OpenAI image generation returned no image data."
                )
            try:
                generated = generated_image_output(encoded, output_index=0)
            except ModelCallError as exc:
                raise FunctionToolError(
                    "OpenAI image generation returned an invalid image."
                ) from exc
            return FunctionToolResult(
                output=[],
                metadata={"provider": "openai", "operation": "image_generation"},
                generated_files=[generated],
            )

        return make_tool(
            image_generation,
            name="image_generation",
            description="Generate one image from a text prompt.",
        )


def openai_images_client_factory(
    config: OpenAIResponsesClientConfig,
) -> OpenAIImagesClientFactory:
    """Bind the existing integration endpoint, credential and account headers."""

    def create() -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            organization=config.organization,
            project=config.project,
            default_headers=config.default_headers,
            max_retries=0,
        )

    return create
