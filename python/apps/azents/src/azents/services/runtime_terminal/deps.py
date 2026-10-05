"""FastAPI composition for the Public Runtime Terminal service."""

import secrets
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.repos.runtime_terminal_authority_read import (
    RuntimeTerminalAuthorityReadRepository,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.deps import (
    get_runtime_coordination_store,
    get_runtime_terminal_control_dispatcher,
    get_runtime_terminal_coordination_store,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_dispatcher import (
    RuntimeTerminalControlDispatcherAdapter,
)
from azents.services.runtime_terminal.authority import (
    DatabaseRuntimeTerminalAuthorityResolver,
)
from azents.services.runtime_terminal.service import RuntimeTerminalService
from azents.services.runtime_terminal.ticket import HmacRuntimeTerminalTicketCodec
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingService,
)
from azents.services.terminal_policy.service import TerminalPolicyResolver


def get_runtime_terminal_authority_resolver(
    authority_repository: Annotated[
        RuntimeTerminalAuthorityReadRepository,
        Depends(RuntimeTerminalAuthorityReadRepository),
    ],
    runtime_coordination: Annotated[
        RuntimeCoordinationStore,
        Depends(get_runtime_coordination_store),
    ],
    working_folder_service: Annotated[
        SessionWorkingFolderBindingService,
        Depends(SessionWorkingFolderBindingService),
    ],
) -> DatabaseRuntimeTerminalAuthorityResolver:
    """Return the deployment-wired current Terminal authority resolver."""
    return DatabaseRuntimeTerminalAuthorityResolver(
        authority_repository=authority_repository,
        runtime_coordination=runtime_coordination,
        working_folder_service=working_folder_service,
        policy_resolver=TerminalPolicyResolver(),
    )


def get_runtime_terminal_service(
    config: Annotated[Config, Depends(get_config)],
    authority_resolver: Annotated[
        DatabaseRuntimeTerminalAuthorityResolver,
        Depends(get_runtime_terminal_authority_resolver),
    ],
    terminal_coordination: Annotated[
        RuntimeTerminalCoordinationStore,
        Depends(get_runtime_terminal_coordination_store),
    ],
    dispatcher: Annotated[
        RuntimeTerminalControlDispatcherAdapter,
        Depends(get_runtime_terminal_control_dispatcher),
    ],
) -> RuntimeTerminalService:
    """Return the deployment-wired Public Runtime Terminal service."""
    return RuntimeTerminalService(
        authority_resolver=authority_resolver,
        coordination=terminal_coordination,
        dispatcher=dispatcher,
        ticket_codec=HmacRuntimeTerminalTicketCodec(
            config.credential_encryption.key.encode()
        ),
        clock=_utc_now,
        ticket_id_factory=_new_id,
        terminal_id_factory=_new_id,
        stream_nonce_factory=lambda: secrets.token_urlsafe(32),
    )


def get_runtime_terminal_web_origin(
    config: Annotated[Config, Depends(get_config)],
) -> str:
    """Return the exact configured Main Web origin for Terminal WebSockets."""
    if config.web_url is None:
        raise RuntimeError("Main Web URL is required for Runtime Terminal")
    parsed = urlsplit(config.web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Main Web URL is required for Runtime Terminal")
    return f"{parsed.scheme}://{parsed.netloc}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid7().hex
