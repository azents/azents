"""Detached Runtime reconciliation collections, repair input and timeout count."""

import dataclasses

from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence

from azents.repos.agent_runtime.data import AgentRuntime


@dataclasses.dataclass(frozen=True)
class RuntimeReconciliationCandidates:
    """The ordered candidate snapshots selected together before dispatch."""

    lifecycle: tuple[AgentRuntime, ...]
    observe: tuple[AgentRuntime, ...]
    configuration_adoption: tuple[AgentRuntime, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeObserveRepairInput:
    """Existing correlated report identities needed by the exact repair read."""

    runtime_id: str
    provider_id: str
    provider_generation: int
    observed_desired_generation: int
    runtime_configuration: RuntimeConfigurationEvidence


@dataclasses.dataclass(frozen=True)
class RuntimeReconciliationTimeouts:
    """Bounded timeout mutation count after connection refresh and dispatch."""

    count: int
