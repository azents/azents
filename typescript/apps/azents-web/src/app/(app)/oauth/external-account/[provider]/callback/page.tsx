/**
 * Authenticated provider identity OAuth callback contract.
 *
 * The Phase 2 route claims the one-time attempt through the server-side tRPC
 * boundary and renders a bounded result. Account-page presentation evolves in
 * the later Web surface phase.
 */

import { Container, Stack, Title } from "@mantine/core";
import { TRPCError } from "@trpc/server";
import { getTranslations } from "next-intl/server";
import { cache } from "react";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { trpc } from "@/trpc/server";
import { CallbackResult } from "../../../mcp/callback/CallbackResult";

type Provider = "slack" | "discord";
type ExchangeResult = { success: true } | { success: false; message: string };

const exchangeOnce = cache(
  async (
    provider: Provider,
    code: string,
    state: string,
  ): Promise<ExchangeResult> => {
    try {
      await trpc.accountLinks.exchangeOauth({ provider, code, state });
      return { success: true };
    } catch (error) {
      if (error instanceof TRPCError) {
        return { success: false, message: error.message };
      }
      throw error;
    }
  },
);

interface PageProps {
  params: Promise<{ provider: string }>;
  searchParams: Promise<Record<string, string | string[] | null>>;
}

function parseProvider(value: string): Provider | null {
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

function providerCallbackMessage(error: string | null): string {
  if (error === "access_denied") {
    return "Provider authorization was cancelled. Restart account connection.";
  }
  return "Provider authorization could not be completed. Restart account connection.";
}

export default async function ExternalAccountOAuthCallbackPage({
  params,
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");
  const [{ provider: providerParam }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  const provider = parseProvider(providerParam);
  const code = typeof query.code === "string" ? query.code : null;
  const state = typeof query.state === "string" ? query.state : null;
  const providerError = typeof query.error === "string" ? query.error : null;

  if (!(await hasLiveAuthSession())) {
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="lg">
          <Title order={2}>{t("title")}</Title>
          <CallbackResult
            success={false}
            message="Sign in to complete account connection, then restart the flow."
            returnHref="/login?next=%2Faccount%2Fexternal-accounts"
          />
        </Stack>
      </Container>
    );
  }

  const result: ExchangeResult =
    provider !== null &&
    providerError === null &&
    code !== null &&
    state !== null
      ? await exchangeOnce(provider, code, state)
      : {
          success: false,
          message:
            providerError !== null
              ? providerCallbackMessage(providerError)
              : "Missing provider, code, or state. Restart account connection.",
        };

  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Title order={2}>{t("title")}</Title>
        <CallbackResult
          success={result.success}
          message={result.success ? null : result.message}
          returnHref="/account/external-accounts"
        />
      </Stack>
    </Container>
  );
}
