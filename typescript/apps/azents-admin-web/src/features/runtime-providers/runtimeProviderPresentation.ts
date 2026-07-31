interface RuntimeProviderContractPointers {
  enabled: boolean;
  lifecycle_state: string;
  current_contract_revision_id: string | null;
}

export interface RuntimeProviderReadiness {
  color: string;
  label: string;
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
