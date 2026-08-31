"""Provider-side Agent Runtime Control contracts and run loop."""

import asyncio
import dataclasses
import enum
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, TypeAlias, assert_never

from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEnvelope,
    RuntimeConfigurationEvidence,
)

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
_LOGGER = logging.getLogger(__name__)
_MIN_HEARTBEAT_CHECK_INTERVAL_SECONDS = 0.01


class RuntimeDesiredState(enum.StrEnum):
    """Final desired Runtime state for reset."""

    RUNNING = "running"
    STOPPED = "stopped"


class RuntimeLifecycleCommandType(enum.StrEnum):
    """Provider lifecycle command types."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RESET = "reset"
    UPDATE_CONFIGURATION = "update_configuration"
    OBSERVE = "observe"
    TERMINAL_DELETE = "terminal_delete"


class RuntimeProviderObservedState(enum.StrEnum):
    """Provider observed Runtime states."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    RESETTING = "resetting"
    FAILED = "failed"


class RuntimeProviderReconciliationStatus(enum.StrEnum):
    """Provider managed-resource comparison status."""

    IN_SYNC = "in_sync"
    DRIFTED = "drifted"


class RuntimeProviderOperationalWarningSeverity(enum.StrEnum):
    """Severity of one warning-only Provider deployment diagnostic."""

    WARNING = "warning"


_RECONCILIATION_KIND_MAX_LENGTH = 128
_RECONCILIATION_REASON_MAX_LENGTH = 256
_RECONCILIATION_DIAGNOSTIC_MAX_ENTRIES = 16
_RECONCILIATION_DIAGNOSTIC_KEY_MAX_LENGTH = 128
_RECONCILIATION_DIAGNOSTIC_VALUE_MAX_LENGTH = 512
RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY = "network_policy"
RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT = "network_enforcement"
_OPERATIONAL_WARNING_MAX_COUNT = 32
_OPERATIONAL_WARNING_CODE_MAX_LENGTH = 128
_OPERATIONAL_WARNING_METADATA_MAX_ENTRIES = 16
_OPERATIONAL_WARNING_METADATA_KEY_MAX_LENGTH = 128
_OPERATIONAL_WARNING_METADATA_VALUE_MAX_LENGTH = 512
_OPERATIONAL_WARNING_METADATA_KEYS = {
    "cni_support_unconfirmed": frozenset({"reason"}),
    "mandatory_service_unavailable": frozenset({"reason", "service_role"}),
    "namespace_default_deny_unconfirmed": frozenset({"reason"}),
    "namespace_identity_unconfirmed": frozenset({"reason"}),
    "proxy_artifact_invalid": frozenset({"artifact_digest", "artifact_role", "reason"}),
    "rbac_incomplete": frozenset({"required_verb", "resource_kind"}),
    "unexpected_network_policy": frozenset({"policy_count"}),
}
_OPERATIONAL_WARNING_RESOURCE_KINDS = frozenset(
    {
        "configmaps",
        "networkpolicies",
        "persistentvolumeclaims",
        "pods",
        "secrets",
        "services",
    }
)
_OPERATIONAL_WARNING_REQUIRED_VERBS = frozenset(
    {"create", "delete", "get", "list", "patch", "update", "watch"}
)
_OPERATIONAL_WARNING_ENUM_VALUES = {
    ("cni_support_unconfirmed", "reason"): frozenset(
        {
            "api_discovery_unavailable",
            "cni_identity_unavailable",
            "network_policy_support_unconfirmed",
        }
    ),
    ("mandatory_service_unavailable", "reason"): frozenset(
        {
            "cluster_ip_unavailable",
            "endpoint_hostname_mismatch",
            "service_missing",
        }
    ),
    ("mandatory_service_unavailable", "service_role"): frozenset(
        {
            "runtime_control",
            "runtime_proxy",
            "runtime_transfer",
        }
    ),
    ("namespace_default_deny_unconfirmed", "reason"): frozenset(
        {
            "policy_missing",
            "policy_ownership_mismatch",
            "policy_selector_mismatch",
        }
    ),
    ("namespace_identity_unconfirmed", "reason"): frozenset(
        {
            "namespace_mismatch",
            "namespace_unavailable",
        }
    ),
    ("proxy_artifact_invalid", "artifact_role"): frozenset(
        {
            "policy_addon",
            "proxy_image",
        }
    ),
    ("proxy_artifact_invalid", "reason"): frozenset(
        {
            "configuration_missing",
            "digest_mismatch",
            "digest_missing",
        }
    ),
}
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SAFE_COUNT = re.compile(r"(0|[1-9][0-9]{0,8})")


@dataclasses.dataclass(frozen=True)
class RuntimeProviderOperationalWarning:
    """One bounded warning from Provider deployment validation."""

    code: str
    severity: RuntimeProviderOperationalWarningSeverity
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        """Validate one warning-only safe diagnostic."""
        _bounded_string(
            self.code,
            "operational warning code",
            _OPERATIONAL_WARNING_CODE_MAX_LENGTH,
        )
        if self.severity is not RuntimeProviderOperationalWarningSeverity.WARNING:
            raise ValueError("operational diagnostic severity must be warning")
        if len(self.metadata) > _OPERATIONAL_WARNING_METADATA_MAX_ENTRIES:
            raise ValueError("operational warning metadata has too many entries")
        allowed_keys = _OPERATIONAL_WARNING_METADATA_KEYS.get(self.code)
        if allowed_keys is None:
            if self.metadata:
                raise ValueError(
                    "unknown operational warning codes cannot include metadata"
                )
            return
        unknown_keys = set(self.metadata) - allowed_keys
        if unknown_keys:
            raise ValueError(
                "operational warning metadata contains unsupported keys: "
                + ", ".join(sorted(unknown_keys))
            )
        for key, value in self.metadata.items():
            _bounded_string(
                key,
                "operational warning metadata key",
                _OPERATIONAL_WARNING_METADATA_KEY_MAX_LENGTH,
            )
            _bounded_string(
                value,
                "operational warning metadata value",
                _OPERATIONAL_WARNING_METADATA_VALUE_MAX_LENGTH,
            )
            _validate_operational_warning_metadata_value(self.code, key, value)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderOperationalDiagnostics:
    """Current warning-only deployment validation snapshot."""

    checked_at: datetime
    warnings: Sequence[RuntimeProviderOperationalWarning]

    def __post_init__(self) -> None:
        """Validate a bounded timezone-aware operational snapshot."""
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError(
                "operational diagnostics checked_at must be timezone-aware"
            )
        if len(self.warnings) > _OPERATIONAL_WARNING_MAX_COUNT:
            raise ValueError("operational diagnostics has too many warnings")
        codes = [warning.code for warning in self.warnings]
        if len(codes) != len(set(codes)):
            raise ValueError("operational warning codes must be unique")


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReconciliationObservation:
    """One bounded Provider comparison of a managed Runtime resource."""

    kind: str
    status: RuntimeProviderReconciliationStatus
    reason: str
    diagnostic: Mapping[str, str]

    def __post_init__(self) -> None:
        """Validate one actionable managed-resource comparison."""
        if not isinstance(self.status, RuntimeProviderReconciliationStatus):
            raise ValueError("reconciliation status is unsupported")
        _bounded_reconciliation_string(
            self.kind,
            "reconciliation kind",
            _RECONCILIATION_KIND_MAX_LENGTH,
        )
        if self.kind not in {
            RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_POLICY,
            RUNTIME_PROVIDER_RECONCILIATION_KIND_NETWORK_ENFORCEMENT,
        }:
            raise ValueError(f"reconciliation kind is unsupported: {self.kind}")
        _bounded_reconciliation_string(
            self.reason,
            "reconciliation reason",
            _RECONCILIATION_REASON_MAX_LENGTH,
        )
        if len(self.diagnostic) > _RECONCILIATION_DIAGNOSTIC_MAX_ENTRIES:
            raise ValueError("reconciliation diagnostic has too many entries")
        for key, value in self.diagnostic.items():
            _bounded_reconciliation_string(
                key,
                "reconciliation diagnostic key",
                _RECONCILIATION_DIAGNOSTIC_KEY_MAX_LENGTH,
            )
            _bounded_reconciliation_string(
                value,
                "reconciliation diagnostic value",
                _RECONCILIATION_DIAGNOSTIC_VALUE_MAX_LENGTH,
            )


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReconciliationEvidence:
    """Authoritative kind-scoped comparison evidence from one Provider report."""

    observations: Sequence[RuntimeProviderReconciliationObservation]

    def __post_init__(self) -> None:
        """Reject an ambiguous or empty reconciliation evidence set."""
        if not self.observations:
            raise ValueError("reconciliation observations must not be empty")
        kinds = [observation.kind for observation in self.observations]
        if len(kinds) != len(set(kinds)):
            raise ValueError("reconciliation observation kinds must be unique")


@dataclasses.dataclass(frozen=True)
class RuntimeIdentity:
    """Runtime identity needed by a Provider command."""

    runtime_id: str
    agent_id: str
    workspace_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeContainerAuth:
    """Auth and connection material injected into the Runtime container."""

    control_endpoint: str
    transfer_endpoint: str
    runner_auth_token: str
    runner_auth_credential_id: str
    control_tls_ca_pem: str | None
    allow_insecure_control: bool


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleCommand:
    """Lifecycle command consumed by an external Runtime Provider."""

    command_type: RuntimeLifecycleCommandType
    identity: RuntimeIdentity
    desired_generation: int
    provider_generation: int
    runner_image: str
    auth: RuntimeContainerAuth
    reset_final_desired_state: RuntimeDesiredState | None
    runtime_configuration: RuntimeConfigurationEnvelope


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReport:
    """Provider observed-state report sent to Control."""

    runtime_id: str
    provider_id: str
    provider_generation: int
    observed_state: RuntimeProviderObservedState
    observed_desired_generation: int
    provider_runtime_id: str | None
    reason: str
    diagnostic: Mapping[str, str]
    reported_at: datetime
    terminal_delete_acknowledged: bool
    runtime_configuration: RuntimeConfigurationEvidence
    reconciliation: RuntimeProviderReconciliationEvidence | None


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleResult:
    """Lifecycle command result plus the report to send to Control."""

    command_type: RuntimeLifecycleCommandType
    report: RuntimeProviderReport


@dataclasses.dataclass(frozen=True)
class ProviderRegistration:
    """Provider registration payload sent to Control."""

    provider_id: str
    provider_type: str
    scope: str
    workspace_id: str | None
    protocol_version: str
    capabilities: Sequence[str]
    config_schema_version: str
    metadata: Mapping[str, JsonValue]
    capability_contract: Mapping[str, JsonValue]
    operational_diagnostics: RuntimeProviderOperationalDiagnostics | None


@dataclasses.dataclass(frozen=True)
class ProviderRegistrationAccepted:
    """Provider registration result issued by Control."""

    provider_id: str
    connection_id: str
    generation: int
    heartbeat_interval_seconds: int


@dataclasses.dataclass(frozen=True)
class ProviderCommandEnvelope:
    """Control request carrying one Provider lifecycle command."""

    request_id: str
    command: RuntimeLifecycleCommand
    deadline_at: datetime | None = None


@dataclasses.dataclass(frozen=True)
class ProviderCommandCompletion:
    """Provider command completion delivered back to Control."""

    request_id: str
    generation: int
    success: bool
    report: RuntimeProviderReport | None
    error_code: str | None
    error_message: str | None
    completed_at: datetime


class ProviderConnectionRejected(RuntimeError):
    """Control rejected a heartbeat or generation fence."""


class ProviderCommandExpired(RuntimeError):
    """Control command deadline elapsed before Provider execution."""


class ProviderControlClient(Protocol):
    """Transport implementation used by the external Provider process."""

    async def register_provider(
        self,
        registration: ProviderRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> ProviderRegistrationAccepted:
        """Register the Provider connection and receive a generation."""
        ...

    async def heartbeat_provider(
        self,
        *,
        provider_id: str,
        generation: int,
        heartbeat_at: datetime,
        operational_diagnostics: RuntimeProviderOperationalDiagnostics | None,
    ) -> bool:
        """Refresh Provider connection TTL for the accepted generation."""
        ...

    async def report_provider_state(self, report: RuntimeProviderReport) -> None:
        """Persist one Provider observed-state report."""
        ...

    async def claim_next_provider_command(
        self,
        *,
        provider_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> ProviderCommandEnvelope | None:
        """Claim the next command assigned to this Provider generation."""
        ...

    async def complete_provider_command(
        self,
        completion: ProviderCommandCompletion,
    ) -> None:
        """Complete a previously claimed command."""
        ...


class RuntimeProviderLifecycle(Protocol):
    """Lifecycle-only backend implementation owned by a Provider."""

    async def start(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Start a Runtime without deleting workspace data."""
        ...

    async def stop(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Stop a Runtime without deleting workspace data."""
        ...

    async def restart(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Restart a Runtime without deleting workspace data."""
        ...

    async def reset(self, command: RuntimeLifecycleCommand) -> RuntimeLifecycleResult:
        """Reset a Runtime; this is the only destructive workspace operation."""
        ...

    async def update_configuration(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Apply a supported in-place Runtime configuration change."""
        ...

    async def terminal_delete(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        """Permanently remove all Provider-owned Runtime resources."""
        ...

    async def observe(self, command: RuntimeLifecycleCommand) -> RuntimeProviderReport:
        """Observe one Runtime."""
        ...

    async def observe_known_runtimes(self) -> Sequence[RuntimeProviderReport]:
        """Observe Provider-owned Runtimes after Provider process restart."""
        ...


Clock: TypeAlias = Callable[[], datetime]
Monotonic: TypeAlias = Callable[[], float]
OperationalDiagnosticsSupplier: TypeAlias = Callable[
    [], RuntimeProviderOperationalDiagnostics | None
]


class ProviderRunLoop:
    """Provider process loop over explicit Control client and lifecycle contracts."""

    def __init__(
        self,
        *,
        client: ProviderControlClient,
        lifecycle: RuntimeProviderLifecycle,
        registration: ProviderRegistration,
        connection_id: str,
        consumer_id: str,
        operational_diagnostics: OperationalDiagnosticsSupplier,
        clock: Clock | None = None,
        monotonic: Monotonic | None = None,
    ) -> None:
        """Initialize the Provider run loop."""
        self._client = client
        self._lifecycle = lifecycle
        self._registration = registration
        self._connection_id = connection_id
        self._consumer_id = consumer_id
        self._operational_diagnostics = operational_diagnostics
        self._clock = clock or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._accepted: ProviderRegistrationAccepted | None = None
        self._last_heartbeat_at: float | None = None

    @property
    def accepted(self) -> ProviderRegistrationAccepted | None:
        """Return the accepted Provider registration, if startup completed."""
        return self._accepted

    async def start(self) -> ProviderRegistrationAccepted:
        """Register the Provider and report all known backend Runtime state."""
        accepted = await self._client.register_provider(
            dataclasses.replace(
                self._registration,
                operational_diagnostics=self._operational_diagnostics(),
            ),
            connection_id=self._connection_id,
            registered_at=self._clock(),
        )
        self._accepted = accepted
        # Refresh the connection before the potentially slow backend resync.
        # The Control registration TTL starts when register_provider completes,
        # so delaying the first heartbeat until after observe_known_runtimes can
        # let a slow Kubernetes API scan expire an otherwise healthy Provider.
        await self.heartbeat(force=True)
        reports = await self._lifecycle.observe_known_runtimes()
        _LOGGER.info(
            "Runtime Provider registered",
            extra={
                "provider_id": accepted.provider_id,
                "connection_id": accepted.connection_id,
                "provider_generation": accepted.generation,
                "known_runtime_count": len(reports),
            },
        )
        for report in reports:
            await self.report_provider_state(report)
        return accepted

    async def report_provider_state(
        self,
        report: RuntimeProviderReport,
    ) -> RuntimeProviderReport:
        """Send backend state under the current Provider connection generation."""
        accepted = self._require_accepted()
        current_report = dataclasses.replace(
            report,
            provider_generation=accepted.generation,
        )
        await self._client.report_provider_state(current_report)
        return current_report

    async def heartbeat(self, *, force: bool = False) -> bool:
        """Send a heartbeat when due and reject stale generations explicitly."""
        accepted = self._require_accepted()
        now = self._monotonic()
        if (
            not force
            and self._last_heartbeat_at is not None
            and now - self._last_heartbeat_at < accepted.heartbeat_interval_seconds
        ):
            return False
        ok = await self._client.heartbeat_provider(
            provider_id=accepted.provider_id,
            generation=accepted.generation,
            heartbeat_at=self._clock(),
            operational_diagnostics=self._operational_diagnostics(),
        )
        if not ok:
            raise ProviderConnectionRejected(
                f"provider generation rejected: {accepted.provider_id}"
            )
        self._last_heartbeat_at = now
        return True

    async def process_next_command(
        self,
        *,
        block_ms: int,
    ) -> ProviderCommandCompletion | None:
        """Claim, execute, and complete one Provider command."""
        accepted = self._require_accepted()
        envelope = await self._client.claim_next_provider_command(
            provider_id=accepted.provider_id,
            generation=accepted.generation,
            consumer_id=self._consumer_id,
            block_ms=block_ms,
        )
        if envelope is None:
            return None
        command = envelope.command
        _LOGGER.info(
            "Runtime Provider command claimed provider_id=%s provider_generation=%s "
            "request_id=%s command=%s resource=runtime/%s agent_id=%s "
            "workspace_id=%s desired_generation=%s",
            accepted.provider_id,
            accepted.generation,
            envelope.request_id,
            command.command_type.value,
            command.identity.runtime_id,
            command.identity.agent_id,
            command.identity.workspace_id,
            command.desired_generation,
        )
        if _deadline_expired(envelope, self._clock()):
            completion = self._expired_completion(envelope, accepted.generation)
            await self._client.complete_provider_command(completion)
            _LOGGER.warning(
                "Runtime Provider command expired before execution provider_id=%s "
                "provider_generation=%s request_id=%s command=%s "
                "resource=runtime/%s desired_generation=%s deadline_at=%s",
                accepted.provider_id,
                accepted.generation,
                envelope.request_id,
                command.command_type.value,
                command.identity.runtime_id,
                command.desired_generation,
                envelope.deadline_at.isoformat()
                if envelope.deadline_at is not None
                else None,
            )
            return completion
        completion = await self._execute_command(envelope, accepted.generation)
        if completion.report is not None:
            completion = dataclasses.replace(
                completion,
                report=dataclasses.replace(
                    completion.report,
                    provider_generation=accepted.generation,
                ),
            )
        await self._client.complete_provider_command(completion)
        _LOGGER.info(
            "Runtime Provider command finished provider_id=%s provider_generation=%s "
            "request_id=%s command=%s resource=runtime/%s desired_generation=%s "
            "success=%s error_code=%s",
            accepted.provider_id,
            accepted.generation,
            envelope.request_id,
            command.command_type.value,
            command.identity.runtime_id,
            command.desired_generation,
            completion.success,
            completion.error_code,
        )
        return completion

    def _expired_completion(
        self,
        envelope: ProviderCommandEnvelope,
        generation: int,
    ) -> ProviderCommandCompletion:
        return ProviderCommandCompletion(
            request_id=envelope.request_id,
            generation=generation,
            success=False,
            report=None,
            error_code="ProviderCommandExpired",
            error_message="Provider command deadline expired before execution",
            completed_at=self._clock(),
        )

    async def run_forever(
        self,
        *,
        stop: asyncio.Event,
        command_block_ms: int = 5_000,
    ) -> None:
        """Run until the caller signals stop or the task is cancelled."""
        if self._accepted is None:
            await self.start()
        heartbeat_task = asyncio.create_task(
            self._run_heartbeat_loop(stop),
            name="runtime-provider-heartbeat",
        )
        command_task = asyncio.create_task(
            self._run_command_loop(stop, command_block_ms=command_block_ms),
            name="runtime-provider-command",
        )
        tasks = (heartbeat_task, command_task)
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                await task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_heartbeat_loop(self, stop: asyncio.Event) -> None:
        """Refresh the Provider lease independently from lifecycle commands."""
        accepted = self._require_accepted()
        check_interval_seconds = max(
            accepted.heartbeat_interval_seconds / 2,
            _MIN_HEARTBEAT_CHECK_INTERVAL_SECONDS,
        )
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=check_interval_seconds,
                )
            except TimeoutError:
                await self.heartbeat()

    async def _run_command_loop(
        self,
        stop: asyncio.Event,
        *,
        command_block_ms: int,
    ) -> None:
        """Execute Provider commands serially while the connection is active."""
        while not stop.is_set():
            await self.process_next_command(block_ms=command_block_ms)

    async def _execute_command(
        self,
        envelope: ProviderCommandEnvelope,
        generation: int,
    ) -> ProviderCommandCompletion:
        try:
            result = await self._dispatch(envelope.command)
            return ProviderCommandCompletion(
                request_id=envelope.request_id,
                generation=generation,
                success=True,
                report=result.report,
                error_code=None,
                error_message=None,
                completed_at=self._clock(),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.exception(
                "Runtime Provider command execution failed request_id=%s command=%s "
                "resource=runtime/%s desired_generation=%s",
                envelope.request_id,
                envelope.command.command_type.value,
                envelope.command.identity.runtime_id,
                envelope.command.desired_generation,
            )
            return ProviderCommandCompletion(
                request_id=envelope.request_id,
                generation=generation,
                success=False,
                report=None,
                error_code=type(exc).__name__,
                error_message=str(exc),
                completed_at=self._clock(),
            )

    async def _dispatch(
        self,
        command: RuntimeLifecycleCommand,
    ) -> RuntimeLifecycleResult:
        match command.command_type:
            case RuntimeLifecycleCommandType.START:
                return await self._lifecycle.start(command)
            case RuntimeLifecycleCommandType.STOP:
                return await self._lifecycle.stop(command)
            case RuntimeLifecycleCommandType.RESTART:
                return await self._lifecycle.restart(command)
            case RuntimeLifecycleCommandType.RESET:
                return await self._lifecycle.reset(command)
            case RuntimeLifecycleCommandType.UPDATE_CONFIGURATION:
                return await self._lifecycle.update_configuration(command)
            case RuntimeLifecycleCommandType.TERMINAL_DELETE:
                return await self._lifecycle.terminal_delete(command)
            case RuntimeLifecycleCommandType.OBSERVE:
                report = await self._lifecycle.observe(command)
                return RuntimeLifecycleResult(
                    command_type=RuntimeLifecycleCommandType.OBSERVE,
                    report=report,
                )
            case _:
                assert_never(command.command_type)

    def _require_accepted(self) -> ProviderRegistrationAccepted:
        accepted = self._accepted
        if accepted is None:
            raise RuntimeError("provider run loop has not registered with Control")
        return accepted


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _deadline_expired(envelope: ProviderCommandEnvelope, now: datetime) -> bool:
    if envelope.deadline_at is None:
        return False
    return envelope.deadline_at <= now


def _bounded_string(value: str, name: str, maximum: int) -> None:
    if not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{name} must not exceed {maximum} characters")


_bounded_reconciliation_string = _bounded_string


def _validate_operational_warning_metadata_value(
    code: str,
    key: str,
    value: str,
) -> None:
    """Validate one non-secret operational diagnostic scalar."""
    if key == "resource_kind":
        if value not in _OPERATIONAL_WARNING_RESOURCE_KINDS:
            raise ValueError("operational warning resource_kind is unsupported")
        return
    if key == "required_verb":
        if value not in _OPERATIONAL_WARNING_REQUIRED_VERBS:
            raise ValueError("operational warning required_verb is unsupported")
        return
    if key == "artifact_digest":
        if _SHA256_DIGEST.fullmatch(value) is None:
            raise ValueError("operational warning artifact_digest must be sha256")
        return
    if key == "policy_count":
        if _SAFE_COUNT.fullmatch(value) is None:
            raise ValueError("operational warning policy_count must be a count")
        return
    allowed_values = _OPERATIONAL_WARNING_ENUM_VALUES.get((code, key))
    if allowed_values is None or value not in allowed_values:
        raise ValueError(f"operational warning {code}.{key} value is unsupported")
