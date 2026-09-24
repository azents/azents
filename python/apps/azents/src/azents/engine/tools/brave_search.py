"""Native Brave Search Toolkit exposing five direct, key-backed search functions."""

from typing import ClassVar, Literal

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from azents.core.tools import (
    BraveSearchToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.brave_search_api import BraveSearchApi, ImageEntry, SearchEntry


class BraveSearchSecrets(BaseModel):
    """API key stored only in ToolkitConfig encrypted credentials."""

    api_key: SecretStr = Field(min_length=1)


class _Query(BaseModel):
    """Shared bounded query and locale controls."""

    q: str = Field(min_length=1, max_length=400)
    country: str | None = Field(default=None, pattern=r"^(ALL|[A-Z]{2})$")
    search_lang: str | None = Field(default=None, pattern=r"^[a-z]{2,5}$")

    @field_validator("q")
    @classmethod
    def check_query_words(cls, value: str) -> str:
        """Follow the provider's common search word limit."""
        if len(value.split()) > 50:
            raise ValueError("Search query exceeds 50 words.")
        return value


class _PagedQuery(_Query):
    """Web, news and video query controls."""

    count: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0, le=9)
    freshness: Literal["pd", "pw", "pm", "py"] | None = None


class _ContextQuery(_Query):
    """Model-ready context uses token and source limits, not page offsets."""

    count: int = Field(default=10, ge=1, le=20)
    maximum_number_of_urls: int = Field(default=5, ge=1, le=20)
    maximum_number_of_tokens: int = Field(default=4096, ge=1024, le=8192)
    freshness: Literal["pd", "pw", "pm", "py"] | None = None


class _ImageQuery(_Query):
    """Image search is not paginated and uses a separate attachment budget."""

    count: int = Field(default=10, ge=1, le=20)


def _params(
    query: _Query,
    config: BraveSearchToolkitConfig,
) -> dict[str, str | int]:
    """Merge validated request and owner-configured defaults."""
    return {
        "q": query.q,
        "country": query.country or config.country,
        "search_lang": query.search_lang or config.search_lang,
        "safesearch": config.safesearch,
    }


def _text_results(kind: str, entries: list[SearchEntry]) -> str:
    """Bound model-visible result text while retaining source attribution."""
    if not entries:
        return f"Brave {kind} search returned no attributable results."
    lines = [f"Brave {kind} results:"]
    used = len(lines[0])
    included = 0
    for rank, entry in enumerate(entries, start=1):
        item = (
            f"{rank}. {entry.title}\n"
            f"   Source: {entry.url}\n"
            f"   {entry.description[:1000]}"
            + (f"\n   Publisher: {entry.source}" if entry.source else "")
            + (f"\n   Date: {entry.age}" if entry.age else "")
        )
        if used + len(item) + 100 > 18_000:
            break
        lines.append(item)
        used += len(item) + 1
        included += 1
    if included < len(entries):
        lines.append(
            f"{len(entries) - included} further results omitted for output limits."
        )
    return "\n".join(lines)


def _image_results(entries: list[ImageEntry]) -> str:
    """Make attachment state, link identity and model capability explicit."""
    if not entries:
        return "Brave image search returned no attributable results."
    lines = [
        "Brave image results. Image pixels are available only to models supporting "
        "image input; a text-only model has NOT visually inspected them. "
        "Attached images are bounded search thumbnails, not original-resolution files."
    ]
    used = len(lines[0])
    included = 0
    for entry in entries:
        label = (
            "thumbnail attached"
            if entry.attachment is not None
            else (entry.unavailable_reason or "not attached (selection budget)")
        )
        item = (
            f"{entry.rank + 1}. {entry.title}\n"
            f"   Image: {entry.image_url}\n"
            f"   Source page: {entry.page_url}\n"
            f"   Preview: {label}"
        )
        if used + len(item) + 100 > 26_000:
            break
        lines.append(item)
        used += len(item) + 1
        included += 1
    if included < len(entries):
        lines.append(
            f"{len(entries) - included} further results omitted for output limits."
        )
    return "\n".join(lines)


class BraveSearchToolkit(Toolkit[BraveSearchToolkitConfig]):
    """Worker-side Toolkit; no managed Runtime or external channel dependency."""

    def __init__(
        self,
        *,
        config: BraveSearchToolkitConfig,
        client: BraveSearchApi,
    ) -> None:
        self._config = config
        self._client = client

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Offer five distinct static native operations to Tool Search."""
        del context

        async def search_web(query: _PagedQuery) -> str:
            """Search Brave Web for ranked pages and source links; not LLM context."""
            params = _params(query, self._config)
            if params["country"] == "ALL":
                params.pop("country")
            params.update({"count": query.count, "offset": query.offset})
            if query.freshness is not None:
                params["freshness"] = query.freshness
            return _text_results("web", await self._client.search("web", params))

        async def search_context(query: _ContextQuery) -> str:
            """Search Brave LLM Context for extracted snippets with source URLs."""
            params = _params(query, self._config)
            if params["country"] == "ALL":
                params.pop("country")
            params.update(
                {
                    "count": query.count,
                    "maximum_number_of_urls": query.maximum_number_of_urls,
                    "maximum_number_of_tokens": query.maximum_number_of_tokens,
                }
            )
            if query.freshness is not None:
                params["freshness"] = query.freshness
            return _text_results(
                "context", await self._client.search("context", params)
            )

        async def search_news(query: _PagedQuery) -> str:
            """Search Brave News for articles with source pages and date metadata."""
            params = _params(query, self._config)
            params.update({"count": query.count, "offset": query.offset})
            if query.freshness is not None:
                params["freshness"] = query.freshness
            return _text_results("news", await self._client.search("news", params))

        async def search_videos(query: _PagedQuery) -> str:
            """Search Brave Videos for attributable video links and descriptions."""
            params = _params(query, self._config)
            params.update({"count": query.count, "offset": query.offset})
            if query.freshness is not None:
                params["freshness"] = query.freshness
            return _text_results("videos", await self._client.search("videos", params))

        async def search_images(query: _ImageQuery) -> FunctionToolResult:
            """Search Brave Images; attach bounded thumbnails in this same result."""
            params = _params(query, self._config)
            params["count"] = query.count
            if params["safesearch"] == "moderate":
                params["safesearch"] = "strict"
            entries = await self._client.search_images(params, attachment_count=4)
            return FunctionToolResult(
                output=_image_results(entries),
                generated_files=[
                    entry.attachment
                    for entry in entries
                    if entry.attachment is not None
                ],
            )

        tools: list[FunctionTool] = [
            make_tool(search_web, input_model=_PagedQuery),
            make_tool(search_context, input_model=_ContextQuery),
            make_tool(search_news, input_model=_PagedQuery),
            make_tool(search_images, input_model=_ImageQuery),
            make_tool(search_videos, input_model=_PagedQuery),
        ]
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)


class BraveSearchToolkitProvider(ToolkitProvider[BraveSearchToolkitConfig]):
    """Resolve an encrypted API key into a direct Brave client."""

    slug: ClassVar[str] = "brave_search"
    name: ClassVar[str] = "Brave Search"
    description: ClassVar[str] = "Direct Web, LLM context, news, image and video search"
    system_prompt: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = BraveSearchToolkitConfig

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None) -> None:
        self._transport = transport

    async def resolve(
        self,
        config: BraveSearchToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[BraveSearchToolkitConfig]:
        """Resolve a valid secret without exposing it in tool arguments."""
        if context.credentials_json is None:
            raise ValueError("Brave Search API key is required.")
        try:
            secret = BraveSearchSecrets.model_validate_json(context.credentials_json)
        except ValidationError:
            raise ValueError("Brave Search API key is invalid.") from None
        key = secret.api_key.get_secret_value().strip()
        if not key:
            raise ValueError("Brave Search API key is required.")
        return BraveSearchToolkit(
            config=config,
            client=BraveSearchApi(
                api_key=key, timeout=config.timeout, transport=self._transport
            ),
        )

    async def validate_credentials(
        self,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Reject absent keys without echoing secret material."""
        try:
            secret = BraveSearchSecrets.model_validate(credentials)
        except ValidationError:
            return "Brave Search API key is required."
        if not secret.api_key.get_secret_value().strip():
            return "Brave Search API key is required."
        return None

    async def test_connection(
        self,
        config: BraveSearchToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Make one quota-consuming minimal Web search after explicit request."""
        del proxy_url
        try:
            if credentials_json is None:
                raise FunctionToolError("Brave Search API key is required.")
            secret = BraveSearchSecrets.model_validate_json(credentials_json)
            key = secret.api_key.get_secret_value().strip()
            if not key:
                raise FunctionToolError("Brave Search API key is required.")
            client = BraveSearchApi(
                api_key=key, timeout=config.timeout, transport=self._transport
            )
            params: dict[str, str | int] = {"q": "connection test", "count": 1}
            if config.country != "ALL":
                params["country"] = config.country
            await client.search("web", params)
            success, message = True, "Brave Search Web connection succeeded."
        except ValidationError:
            success, message = False, "Brave Search API key is invalid."
        except FunctionToolError as exc:
            success, message = False, str(exc)
        return TestConnectionResult(
            success=success,
            message=message,
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
