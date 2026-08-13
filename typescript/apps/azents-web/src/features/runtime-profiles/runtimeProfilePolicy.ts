import type { RuntimeProfileFormValues } from "./schemas";
import type {
  RuntimeNetworkProjection,
  SelectableInfrastructureProfileResponse,
} from "@azents/public-client";

export type RuntimeProfileMutationPolicy =
  | {
      schemaVersion: 1;
      networkRestriction: {
        allowedCidrs: string[];
        deniedCidrs: string[];
      } | null;
    }
  | {
      schemaVersion: 2;
      networkRestriction:
        | { mode: "inherit" }
        | {
            mode: "direct";
            allowedCidrs: string[];
            deniedCidrs: string[];
          }
        | {
            mode: "proxy_required";
            allowedCidrs: string[];
            deniedCidrs: string[];
            domainPolicy:
              | {
                  mode: "unrestricted";
                  allowedDomains: [];
                  deniedDomains: string[];
                }
              | {
                  mode: "allowlist";
                  allowedDomains: string[];
                  deniedDomains: string[];
                };
          }
        | { mode: "no_network" };
    };

function parseLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function policySchemaVersionForInfrastructure(
  profile: Pick<SelectableInfrastructureProfileResponse, "profile_kind">,
): 1 | 2 {
  return profile.profile_kind === "docker_container" ? 1 : 2;
}

export function proxyDomainModeForInfrastructure(
  network: Pick<RuntimeNetworkProjection, "domain_mode"> | null,
): RuntimeProfileFormValues["proxyDomainMode"] {
  return network?.domain_mode === "allowlist" ? "allowlist" : "unrestricted";
}

export function runtimeProfileMutationPolicy(
  values: RuntimeProfileFormValues,
): RuntimeProfileMutationPolicy {
  const allowedCidrs = parseLines(values.allowedCidrs);
  const deniedCidrs = parseLines(values.deniedCidrs);
  if (values.policySchemaVersion === 1) {
    return {
      schemaVersion: 1,
      networkRestriction:
        values.networkMode === "inherit" ? null : { allowedCidrs, deniedCidrs },
    };
  }
  if (values.networkMode === "inherit" || values.networkMode === "no_network") {
    return {
      schemaVersion: 2,
      networkRestriction: { mode: values.networkMode },
    };
  }
  if (values.networkMode === "direct") {
    return {
      schemaVersion: 2,
      networkRestriction: {
        mode: "direct",
        allowedCidrs,
        deniedCidrs,
      },
    };
  }
  const deniedDomains = parseLines(values.deniedDomains);
  return {
    schemaVersion: 2,
    networkRestriction: {
      mode: "proxy_required",
      allowedCidrs,
      deniedCidrs,
      domainPolicy:
        values.proxyDomainMode === "allowlist"
          ? {
              mode: "allowlist",
              allowedDomains: parseLines(values.allowedDomains),
              deniedDomains,
            }
          : {
              mode: "unrestricted",
              allowedDomains: [],
              deniedDomains,
            },
    },
  };
}
