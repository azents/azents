"""Official OpenAI client configuration shared by listing and inference."""

import dataclasses
import os
from collections.abc import Mapping

from azents.core.enums import LLMProvider
from azents.core.type_guards import is_string_string_dict


@dataclasses.dataclass(frozen=True)
class OpenAIResponsesClientConfig:
    """Credential-bearing configuration kept outside logical requests."""

    api_key: str | None
    base_url: str | None
    organization: str | None
    project: str | None
    default_headers: dict[str, str] | None


def openai_responses_client_config(
    *,
    provider: LLMProvider,
    credential_kwargs: Mapping[str, object],
) -> OpenAIResponsesClientConfig:
    """Build official SDK client configuration from resolved credentials.

    :param provider: selected integration provider identity
    :param credential_kwargs: resolved credential and endpoint configuration
    :returns: client configuration with the existing environment precedence
    """
    api_key = _optional_credential_string(credential_kwargs, "api_key")
    base_url = _optional_credential_string(credential_kwargs, "base_url")
    if base_url is None:
        base_url = _optional_credential_string(credential_kwargs, "api_base")
    if base_url is None and provider == LLMProvider.OPENAI:
        base_url = os.environ.get("AZ_OPENAI_BASE_URL")
    if base_url is None:
        base_url = os.environ.get("OPENAI_BASE_URL")
    organization = _optional_credential_string(credential_kwargs, "organization")
    if organization is None:
        organization = os.environ.get("OPENAI_ORG_ID")
    project = _optional_credential_string(credential_kwargs, "project")
    if project is None:
        project = os.environ.get("OPENAI_PROJECT_ID")
    environment_headers = _openai_custom_headers_from_environment()
    credential_headers = openai_credential_headers(
        credential_kwargs.get("extra_headers")
    )
    default_headers = {
        **(environment_headers or {}),
        **(credential_headers or {}),
    } or None
    return OpenAIResponsesClientConfig(
        api_key=api_key,
        base_url=base_url,
        organization=organization,
        project=project,
        default_headers=default_headers,
    )


def openai_credential_headers(value: object) -> dict[str, str] | None:
    """Validate and copy resolved SDK credential headers.

    :param value: optional resolved header mapping
    :returns: an independent header mapping or no supplied headers
    :raises TypeError: when header keys or values are not strings
    """
    if value is None:
        return None
    if not is_string_string_dict(value):
        raise TypeError("OpenAI client extra_headers must be dict[str, str]")
    return dict(value)


def _optional_credential_string(
    values: Mapping[str, object],
    key: str,
) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"OpenAI client option {key} must be a string")
    return value


def _openai_custom_headers_from_environment() -> dict[str, str] | None:
    """Parse the public SDK's newline-delimited custom-header environment form."""
    raw_headers = os.environ.get("OPENAI_CUSTOM_HEADERS")
    if raw_headers is None:
        return None
    headers: dict[str, str] = {}
    for line in raw_headers.split("\n"):
        separator = line.find(":")
        if separator >= 0:
            headers[line[:separator].strip()] = line[separator + 1 :].strip()
    return headers or None
