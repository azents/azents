"""Worker transfer dependency composition tests."""

from types import SimpleNamespace

import pytest
from azcommon.infra.s3.service import S3Service
from azents_runtime_control.grpc_transfer_coordinator_client import (
    GrpcRuntimeTransferCoordinatorClient,
)

from azents.core.config import Config
from azents.runtime.transfer.runtime_to_server import RuntimeToServerTransferService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.worker.deps import (
    create_worker_external_channel_inbound_staging_configuration,
    create_worker_transfer_services,
)


class _S3Service(S3Service):
    """S3 service test double for dependency validation paths."""

    def __init__(self) -> None:
        """Avoid constructing a real S3 client."""


class _ExchangeFileService(ExchangeFileService):
    """Exchange file service test double for dependency validation paths."""

    def __init__(self) -> None:
        """Avoid constructing a real storage service."""


class _ModelFileService(ModelFileService):
    """Model file service test double for dependency validation paths."""

    def __init__(self) -> None:
        """Avoid constructing a real storage service."""


class _Coordinator(GrpcRuntimeTransferCoordinatorClient):
    """Transfer Coordinator test double for dependency composition."""

    def __init__(self) -> None:
        """Avoid opening a gRPC channel."""


def _config(
    *,
    bucket: str = "workspace-bucket",
    transfer_object_prefix: str = "runtime-transfer",
) -> Config:
    return Config.model_construct(
        workspace_s3=SimpleNamespace(bucket=bucket, prefix="v1"),
        runtime_transfer_coordinator=SimpleNamespace(
            object_prefix=transfer_object_prefix
        ),
    )


def test_worker_transfer_services_require_coordinator() -> None:
    """The Worker cannot start Runtime file services without its Coordinator."""
    with pytest.raises(RuntimeError, match="Coordinator is required"):
        create_worker_transfer_services(
            config=_config(),
            coordinator=None,
            s3_service=_S3Service(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=_ModelFileService(),
        )


def test_worker_transfer_services_share_only_the_injected_coordinator() -> None:
    """All feature services use the supplied Coordinator and bounded dependencies."""
    coordinator = _Coordinator()
    services = create_worker_transfer_services(
        config=_config(),
        coordinator=coordinator,
        s3_service=_S3Service(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
    )

    assert services.server_to_runtime is not None
    assert services.server_to_runtime.coordinator is coordinator
    assert services.present_file_publication is not None
    runtime_to_server = services.present_file_publication.transfer_service
    assert isinstance(runtime_to_server, RuntimeToServerTransferService)
    assert runtime_to_server.coordinator is coordinator
    assert services.provider_delivery is not None
    assert services.provider_delivery.batch_service.coordinator is coordinator
    assert services.import_staging is not None
    assert services.import_staging.transfer_object_prefix == "v1/runtime-transfer"


def test_external_channel_staging_requires_the_worker_coordinator() -> None:
    """Inbound provider bytes cannot stage without Worker Coordinator trust."""
    with pytest.raises(RuntimeError, match="Coordinator is required"):
        create_worker_external_channel_inbound_staging_configuration(
            config=_config(),
            coordinator=None,
            s3_service=_S3Service(),
        )


def test_external_channel_staging_uses_the_bounded_transfer_namespace() -> None:
    """Inbound provider staging shares the bounded Worker transfer storage seam."""
    configuration = create_worker_external_channel_inbound_staging_configuration(
        config=_config(),
        coordinator=_Coordinator(),
        s3_service=_S3Service(),
    )

    assert configuration is not None
    assert configuration.workspace_bucket == "workspace-bucket"
    assert configuration.transfer_object_prefix == "v1/runtime-transfer"
    assert configuration.stream_chunk_size == 256 * 1024
    assert configuration.multipart_part_size == 5 * 1024 * 1024


def test_worker_transfer_services_use_the_configured_transfer_object_prefix() -> None:
    """Worker and Runtime Control can select one shared internal namespace."""
    services = create_worker_transfer_services(
        config=_config(transfer_object_prefix="runtime-transfer-v2"),
        coordinator=_Coordinator(),
        s3_service=_S3Service(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
    )

    assert services.import_staging is not None
    assert services.import_staging.transfer_object_prefix == "v1/runtime-transfer-v2"
