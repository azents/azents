"""Validate typed infrastructure Profiles against current Provider capability."""

import dataclasses
from typing import Any

from pydantic import ValidationError

from azents.core.enums import RuntimeProviderKind
from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileInternalSpec,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileCompatibility,
    canonicalize_runtime_profile_document,
    digest_runtime_profile_document,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
    required_runtime_profile_capabilities,
)
from azents.core.runtime_provider_contract import RuntimeProviderCapabilityContract


@dataclasses.dataclass(frozen=True)
class PreparedRuntimeInfrastructureProfile:
    """Validated canonical values ready for Profile persistence."""

    spec: RuntimeInfrastructureProfileInternalSpec
    canonical_spec: dict[str, Any]
    required_capabilities: tuple[str, ...]
    digest: str
    compatibility: RuntimeProfileCompatibility


@dataclasses.dataclass
class RuntimeProfileCompatibilityUnavailable(Exception):
    """A Profile document cannot be used with the selected Provider."""

    code: str
    missing_capabilities: tuple[str, ...]
    incompatible_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code)


class RuntimeProfileCompatibilityService:
    """Prepare typed Profiles using one current Provider advertisement."""

    def prepare_infrastructure_profile(
        self,
        *,
        provider_kind: RuntimeProviderKind,
        provider_contract_payload: dict[str, Any],
        profile_spec_payload: dict[str, Any],
    ) -> PreparedRuntimeInfrastructureProfile:
        """Validate ownership kind, schema family, and required capabilities."""
        try:
            provider_contract = RuntimeProviderCapabilityContract.model_validate(
                provider_contract_payload
            )
            spec = parse_runtime_infrastructure_profile_spec(profile_spec_payload)
        except ValidationError as error:
            raise RuntimeProfileCompatibilityUnavailable(
                code="profile_document_invalid",
                missing_capabilities=(),
                incompatible_constraints=(),
            ) from error
        if provider_contract.implementation_key != provider_kind.value:
            raise RuntimeProfileCompatibilityUnavailable(
                code="provider_contract_identity_mismatch",
                missing_capabilities=(),
                incompatible_constraints=(),
            )
        expected_profile_kind = _profile_kind_for_provider(provider_kind)
        if spec.profile_kind is not expected_profile_kind:
            raise RuntimeProfileCompatibilityUnavailable(
                code="profile_provider_kind_mismatch",
                missing_capabilities=(),
                incompatible_constraints=(),
            )
        compatibility = evaluate_runtime_profile_compatibility(
            spec,
            provider_contract.profile_contracts,
            provider_protocol_version=provider_contract.protocol_version,
        )
        if not compatibility.compatible:
            raise RuntimeProfileCompatibilityUnavailable(
                code=compatibility.reason_code or "profile_incompatible",
                missing_capabilities=compatibility.missing_capabilities,
                incompatible_constraints=compatibility.incompatible_constraints,
            )
        canonical_spec = canonicalize_runtime_profile_document(spec)
        return PreparedRuntimeInfrastructureProfile(
            spec=spec,
            canonical_spec=canonical_spec,
            required_capabilities=tuple(
                sorted(required_runtime_profile_capabilities(spec))
            ),
            digest=digest_runtime_profile_document(spec),
            compatibility=compatibility,
        )


def _profile_kind_for_provider(
    provider_kind: RuntimeProviderKind,
) -> RuntimeInfrastructureProfileKind:
    if provider_kind is RuntimeProviderKind.KUBERNETES:
        return RuntimeInfrastructureProfileKind.KUBERNETES_POD
    if provider_kind is RuntimeProviderKind.DOCKER:
        return RuntimeInfrastructureProfileKind.DOCKER_CONTAINER
    raise RuntimeProfileCompatibilityUnavailable(
        code="profile_provider_kind_unsupported",
        missing_capabilities=(),
        incompatible_constraints=(),
    )
