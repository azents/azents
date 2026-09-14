import type {
  ExternalAccountProvider,
  ExternalAccountProviderAvailability,
} from "./types";
import type { AccountLinkProviderAvailabilityResponse } from "@azents/public-client";

export type ElevationScreenState = "loading" | "ready" | "error";

export function elevationScreenState({
  hasResponse,
  isError,
}: {
  hasResponse: boolean;
  isError: boolean;
}): ElevationScreenState {
  if (hasResponse) {
    return "ready";
  }
  return isError ? "error" : "loading";
}

function providerAvailability(
  provider: ExternalAccountProvider,
  items: AccountLinkProviderAvailabilityResponse[],
): ExternalAccountProviderAvailability | null {
  const item = items.find((candidate) => candidate.provider === provider);
  return item == null
    ? null
    : {
        provider: item.provider,
        status: item.status,
        available: item.available,
      };
}

export function normalizeProviderAvailability(
  items: AccountLinkProviderAvailabilityResponse[],
): ExternalAccountProviderAvailability[] | null {
  const slack = providerAvailability("slack", items);
  const discord = providerAvailability("discord", items);
  if (slack === null || discord === null) {
    return null;
  }
  return [slack, discord].filter(
    (availability): availability is ExternalAccountProviderAvailability =>
      availability.available,
  );
}
