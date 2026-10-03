"""xAI native search declarations through public OpenAI model settings."""

from openai.types.responses import WebSearchToolParam
from openai.types.responses.web_search_tool_param import Filters
from pydantic_ai.native_tools import WebSearchTool


class _SearchFilters(Filters, total=False):
    """Preserve the public model's blocked-domain option missing from SDK types."""

    blocked_domains: list[str]


def xai_web_search_declaration(tool: WebSearchTool) -> WebSearchToolParam:
    """Retain search options while omitting OpenAI-only search context size."""
    declaration: WebSearchToolParam = {"type": "web_search"}
    if tool.user_location is not None:
        declaration["user_location"] = {"type": "approximate", **tool.user_location}
    filters: _SearchFilters = {}
    if tool.allowed_domains:
        filters["allowed_domains"] = list(tool.allowed_domains)
    if tool.blocked_domains:
        filters["blocked_domains"] = list(tool.blocked_domains)
    if filters:
        declaration["filters"] = filters
    if tool.external_web_access is not None:
        declaration["external_web_access"] = tool.external_web_access
    return declaration
