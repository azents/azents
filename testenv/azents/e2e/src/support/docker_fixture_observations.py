"""Validated projections of the Docker SDK fields consumed by E2E fixtures."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class DockerWaitObservation(BaseModel):
    """The required exit status; Docker-owned errors and extensions stay opaque."""

    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    status_code: StrictInt = Field(alias="StatusCode")


class DockerNetworkAddressObservation(BaseModel):
    """The selected network's address, including the valid empty-address state."""

    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    ip_address: StrictStr = Field(alias="IPAddress")


class _NetworkSettingsObservation(BaseModel):
    """Keep unrelated network entries opaque until the selected entry is decoded."""

    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    networks: dict[str, object] = Field(alias="Networks")


class _ContainerNetworksObservation(BaseModel):
    """The inspect envelope needed to locate one explicitly selected network."""

    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    network_settings: _NetworkSettingsObservation = Field(alias="NetworkSettings")


def decode_docker_network_address(
    attributes: object, *, network_name: str
) -> DockerNetworkAddressObservation:
    """Validate inspect data at ingress without choosing a fallback network."""
    inventory = _ContainerNetworksObservation.model_validate(attributes)
    return DockerNetworkAddressObservation.model_validate(
        inventory.network_settings.networks[network_name]
    )
