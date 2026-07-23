"""Reconcile and enroll one Kubernetes Runtime Provider bootstrap declaration."""

import argparse
import asyncio
import logging
from pathlib import Path
from typing import cast

from azcommon import di
from azcommon.logging import configure_logging_for_runtime
from kubernetes_asyncio.client import ApiClient, CoreV1Api
from kubernetes_asyncio.config import load_incluster_config

from azents.app import run_with_container
from azents.core.config import Config
from azents.services.runtime_provider_bootstrap.enrollment import (
    RuntimeProviderBootstrapEnrollmentService,
)
from azents.services.runtime_provider_bootstrap.helm_file import (
    HelmFileRuntimeProviderBootstrapAdapter,
)
from azents.services.runtime_provider_bootstrap.kubernetes_secret import (
    KubernetesSecretApi,
    read_runtime_provider_credential,
    write_runtime_provider_credential,
)

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile one trusted Runtime Provider declaration and ensure its "
            "Kubernetes credential Secret."
        )
    )
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--source-path", required=True, type=Path)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--secret-namespace", required=True)
    parser.add_argument("--secret-name", required=True)
    parser.add_argument("--secret-key", required=True)
    return parser


async def _run(
    args: argparse.Namespace,
    *,
    config: Config,
    container: di.Container,
) -> None:
    load_incluster_config()
    api_client = ApiClient()
    try:
        api = cast(KubernetesSecretApi, CoreV1Api(api_client))
        existing = await read_runtime_provider_credential(
            api,
            namespace=args.secret_namespace,
            secret_name=args.secret_name,
            secret_key=args.secret_key,
        )
        snapshot = await HelmFileRuntimeProviderBootstrapAdapter(
            source_key=args.source_key,
            path=args.source_path,
        ).read_snapshot()
        service = await container.solve(RuntimeProviderBootstrapEnrollmentService)
        ensured = await service.ensure_credential(
            snapshot=snapshot,
            provider_logical_id=args.provider_id,
            existing_secret=existing,
        )
        if ensured.changed:
            await write_runtime_provider_credential(
                api,
                namespace=args.secret_namespace,
                secret_name=args.secret_name,
                secret_key=args.secret_key,
                provider_logical_id=args.provider_id,
                credential=ensured.secret,
            )
            await service.revoke_superseded(ensured.revoke_after_write)
        logger.info(
            "Runtime Provider bootstrap credential is active",
            extra={
                "provider_id": args.provider_id,
                "secret_namespace": args.secret_namespace,
                "secret_name": args.secret_name,
                "credential_changed": ensured.changed,
                "runtime_env": config.runtime_env.value,
            },
        )
    finally:
        await api_client.close()


async def _async_main(args: argparse.Namespace) -> None:
    config = Config.from_env()
    configure_logging_for_runtime(
        runtime_env=config.runtime_env,
        inhouse_name="azents",
        configure_uvicorn=False,
        sentry_dsn=config.sentry_dsn,
    )
    async with run_with_container(config) as container:
        await _run(args, config=config, container=container)


def main() -> None:
    """Run the Runtime Provider bootstrap credential command."""
    asyncio.run(_async_main(_parser().parse_args()))


if __name__ == "__main__":
    main()
