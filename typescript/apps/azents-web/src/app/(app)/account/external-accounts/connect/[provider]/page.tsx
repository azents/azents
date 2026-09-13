import { TRPCError } from "@trpc/server";
import { redirect } from "next/navigation";
import { ExternalAccountOAuthResult } from "@/features/external-account-links/components/ExternalAccountOAuthResult";
import { trpc } from "@/trpc/server";
import type {
  AccountLinkFailureReason,
  ExternalAccountOAuthResultState,
  ExternalAccountProvider,
} from "@/features/external-account-links/types";

interface PageProps {
  params: Promise<{ provider: string }>;
}

function parseProvider(value: string): ExternalAccountProvider | null {
  return value === "slack" || value === "discord" ? value : null;
}

function failedState(
  provider: ExternalAccountProvider,
  reason: AccountLinkFailureReason,
): ExternalAccountOAuthResultState {
  return { type: "FAILED", provider, reason };
}

export default async function Page({
  params,
}: PageProps): Promise<React.ReactElement> {
  const { provider: providerParam } = await params;
  const provider = parseProvider(providerParam);

  if (provider === null) {
    return (
      <ExternalAccountOAuthResult
        state={{ type: "FAILED", provider: null, reason: "invalid_provider" }}
      />
    );
  }

  try {
    const availability = await trpc.accountLinks.listProviders();
    const providerAvailability = availability.items.find(
      (item) => item.provider === provider,
    );
    if (providerAvailability == null || !providerAvailability.available) {
      return (
        <ExternalAccountOAuthResult
          state={{
            type: "PROVIDER_UNAVAILABLE",
            provider,
            status: providerAvailability?.status ?? "unavailable",
          }}
        />
      );
    }

    const result = await trpc.accountLinks.startOauth({ provider });
    if (result.type === "FAILURE") {
      return (
        <ExternalAccountOAuthResult
          state={
            result.reason === "provider_unavailable"
              ? {
                  type: "PROVIDER_UNAVAILABLE",
                  provider,
                  status: providerAvailability.status,
                }
              : failedState(provider, result.reason)
          }
        />
      );
    }

    redirect(result.data.authorization_url);
  } catch (error) {
    if (!(error instanceof TRPCError)) {
      throw error;
    }
    return (
      <ExternalAccountOAuthResult
        state={failedState(provider, "provider_unavailable")}
      />
    );
  }
}
