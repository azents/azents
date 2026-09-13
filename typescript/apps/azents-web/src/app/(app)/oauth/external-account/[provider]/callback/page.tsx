import { TRPCError } from "@trpc/server";
import { cache } from "react";
import { ExternalAccountOAuthResult } from "@/features/external-account-links/components/ExternalAccountOAuthResult";
import { parseExternalAccountOAuthCallbackQuery } from "@/features/external-account-links/oauth-callback-query";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { trpc } from "@/trpc/server";
import type {
  ExternalAccountOAuthResultState,
  ExternalAccountProvider,
} from "@/features/external-account-links/types";

type ExchangeResult = ExternalAccountOAuthResultState;

const exchangeOnce = cache(
  async (
    provider: ExternalAccountProvider,
    code: string,
    state: string,
  ): Promise<ExchangeResult> => {
    try {
      const result = await trpc.accountLinks.exchangeOauth({
        provider,
        code,
        state,
      });
      return result.type === "SUCCESS"
        ? {
            type: "CONNECTED",
            provider: result.data.provider,
            externalDisplayLabel: result.data.provider_display_label,
            providerTeamLabel: result.data.provider_tenant_display_label,
          }
        : { type: "FAILED", provider, reason: result.reason };
    } catch (error) {
      if (error instanceof TRPCError) {
        return { type: "FAILED", provider, reason: "provider_rejected" };
      }
      throw error;
    }
  },
);

interface PageProps {
  params: Promise<{ provider: string }>;
  searchParams: Promise<Record<string, string | string[] | null>>;
}

function parseProvider(value: string): ExternalAccountProvider | null {
  return value === "slack" || value === "discord" ? value : null;
}

async function hasLiveAuthSession(): Promise<boolean> {
  const authState = await getInitialAuthState();
  if (authState.status !== "authenticated") {
    return false;
  }
  try {
    await trpc.user.me();
    return true;
  } catch (error) {
    if (error instanceof TRPCError && error.code === "UNAUTHORIZED") {
      return false;
    }
    throw error;
  }
}

export default async function Page({
  params,
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const [{ provider: providerParam }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  const provider = parseProvider(providerParam);

  if (!(await hasLiveAuthSession())) {
    return <ExternalAccountOAuthResult state={{ type: "AUTH_REQUIRED" }} />;
  }
  if (provider === null) {
    return (
      <ExternalAccountOAuthResult
        state={{ type: "FAILED", provider: null, reason: "invalid_provider" }}
      />
    );
  }

  const callback = parseExternalAccountOAuthCallbackQuery(query);
  if (callback.type === "CANCELLED") {
    return (
      <ExternalAccountOAuthResult state={{ type: "CANCELLED", provider }} />
    );
  }
  if (callback.type === "PROVIDER_REJECTED") {
    return (
      <ExternalAccountOAuthResult
        state={{ type: "FAILED", provider, reason: "provider_rejected" }}
      />
    );
  }
  if (callback.type === "INVALID") {
    return (
      <ExternalAccountOAuthResult
        state={{ type: "FAILED", provider, reason: "invalid_callback" }}
      />
    );
  }

  const result: ExchangeResult = await exchangeOnce(
    provider,
    callback.code,
    callback.state,
  );

  return <ExternalAccountOAuthResult state={result} />;
}
