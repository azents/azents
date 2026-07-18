"""Shared xAI provider configuration."""

import os

XAI_API_BASE_URL = "https://api.x.ai/v1"


def resolve_xai_api_base_url() -> str:
    """Return the configured xAI API base URL."""
    return os.environ.get("AZ_XAI_API_BASE_URL", XAI_API_BASE_URL).rstrip("/")
