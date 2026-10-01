"""Default official SDK constructor composition for all model operations."""

from azents.core.enums import LLMProvider
from azents.engine.events.openai_responses import create_openai_responses_client
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import ProviderModelFactory


def build_provider_model_factory(
    *,
    provider: LLMProvider,
    credential_kwargs: dict[str, object],
) -> ProviderModelFactory:
    """Create the ordinary owned factory without a fixture transport."""
    return ProviderModelFactory(
        provider=provider,
        credential_kwargs=credential_kwargs,
        sdk_failure_mapper=map_model_provider_error,
        sdk_error_types=SDK_PROVIDER_ERRORS,
        transports=None,
    )


def get_model_sdk_factories() -> ModelSDKFactories:
    """Supply pure SDK constructors through the existing DI composition root."""
    return ModelSDKFactories(
        openai_responses=create_openai_responses_client,
        provider_model=build_provider_model_factory,
    )
