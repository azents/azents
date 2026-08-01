interface RuntimeProviderContractPointers {
  enabled: boolean;
  lifecycle_state: string;
  current_contract_revision_id: string | null;
}

export type InfrastructureProfileKind = "kubernetes_pod" | "docker_container";

export interface RuntimeProviderReadiness {
  color: string;
  label: string;
}

export function infrastructureProfileKindForProvider(
  providerKind: string,
): InfrastructureProfileKind | null {
  if (providerKind === "kubernetes") {
    return "kubernetes_pod";
  }
  if (providerKind === "docker") {
    return "docker_container";
  }
  return null;
}

export function runtimeProviderReadiness(
  provider: RuntimeProviderContractPointers,
): RuntimeProviderReadiness {
  if (!provider.enabled) {
    return { color: "gray", label: "Disabled" };
  }
  if (provider.lifecycle_state !== "active") {
    return { color: "gray", label: provider.lifecycle_state };
  }
  if (provider.current_contract_revision_id === null) {
    return { color: "yellow", label: "Contract pending" };
  }
  return { color: "green", label: "Ready" };
}
