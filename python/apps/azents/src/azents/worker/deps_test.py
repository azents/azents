"""Worker transfer dependency composition tests."""

from types import SimpleNamespace
from typing import cast

from azcommon.infra.s3.service import S3Service
from azents_runtime_control.grpc_transfer_coordinator_client import (
    GrpcRuntimeTransferCoordinatorClient,
)

from azents.core.config import Config
from azents.runtime.transfer.runtime_to_server import RuntimeToServerTransferService
from azents.services.exchange_file import ExchangeFileService
from azents.worker.deps import (
    create_worker_external_channel_inbound_staging_configuration,
    create_worker_transfer_services,
)


def _config(
    *,
    bucket: str = "workspace-bucket",
    transfer_object_prefix: str = "runtime-transfer",
) -> Config:
    return cast(
        Config,
        SimpleNamespace(
            workspace_s3=SimpleNamespace(bucket=bucket, prefix="v1"),
            runtime_transfer_coordinator=SimpleNamespace(
                object_prefix=transfer_object_prefix
            ),
        ),
    )


def test_worker_transfer_services_remain_absent_without_coordinator() -> None:
    """No local state or storage fallback is composed without Coordinator trust."""
    services = create_worker_transfer_services(
        config=_config(),
        coordinator=None,
        s3_service=cast(S3Service, object()),
        exchange_file_service=cast(ExchangeFileService, object()),
    )

    assert services.server_to_runtime is None
    assert services.present_file_publication is None
    assert services.provider_delivery is None
    assert services.import_staging is None


def test_worker_transfer_services_share_only_the_injected_coordinator() -> None:
    """All feature services use the supplied Coordinator and bounded dependencies."""
    coordinator = cast(GrpcRuntimeTransferCoordinatorClient, object())
    services = create_worker_transfer_services(
        config=_config(),
        coordinator=coordinator,
        s3_service=cast(S3Service, object()),
        exchange_file_service=cast(ExchangeFileService, object()),
    )

    assert services.server_to_runtime is not None
    assert services.server_to_runtime.coordinator is coordinator
    assert services.present_file_publication is not None
    runtime_to_server = cast(
        RuntimeToServerTransferService,
        services.present_file_publication.transfer_service,
    )
    assert runtime_to_server.coordinator is coordinator
    assert services.provider_delivery is not None
    assert services.provider_delivery.batch_service.coordinator is coordinator
    assert services.import_staging is not None
    assert services.import_staging.transfer_object_prefix == "v1/runtime-transfer"


def test_external_channel_staging_requires_the_worker_coordinator() -> None:
    """Inbound provider bytes cannot stage without Worker Coordinator trust."""
    assert (
        create_worker_external_channel_inbound_staging_configuration(
            config=_config(),
            coordinator=None,
            s3_service=cast(S3Service, object()),
        )
        is None
    )


def test_external_channel_staging_uses_the_bounded_transfer_namespace() -> None:
    """Inbound provider staging shares the bounded Worker transfer storage seam."""
    configuration = create_worker_external_channel_inbound_staging_configuration(
        config=_config(),
        coordinator=cast(GrpcRuntimeTransferCoordinatorClient, object()),
        s3_service=cast(S3Service, object()),
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
        coordinator=cast(GrpcRuntimeTransferCoordinatorClient, object()),
        s3_service=cast(S3Service, object()),
        exchange_file_service=cast(ExchangeFileService, object()),
    )

    assert services.import_staging is not None
    assert services.import_staging.transfer_object_prefix == "v1/runtime-transfer-v2"
