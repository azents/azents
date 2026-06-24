/**
 * MCP OAuth2 callback server component.
 *
 * Receives code/state from OAuth provider and requests token exchange to backend,
 * then passes result to client component (CallbackResult).
 *
 * authorization code is one-time-use, so React.cache prevents duplicate calls.
 */

import { Container, Stack, Title } from "@mantine/core";
import { TRPCError } from "@trpc/server";
import { getTranslations } from "next-intl/server";
import { cache } from "react";
import { trpc } from "@/trpc/server";
import { CallbackResult } from "./CallbackResult";

type ExchangeResult = { success: true } | { success: false; message: string };

/** authorization code is one-time-use — prevent duplicate calls in same render cycle */
const exchangeOnce = cache(
  async (
    handle: string,
    toolkitConfigId: string,
    code: string,
    state: string,
  ): Promise<ExchangeResult> => {
    try {
      await trpc.toolkit.oauthExchange({
        handle,
        toolkitConfigId,
        code,
        state,
      });
      return { success: true };
    } catch (e) {
      if (e instanceof TRPCError) {
        return { success: false, message: e.message };
      }
      throw e;
    }
  },
);

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | null>>;
}

export default async function OAuthMcpCallbackPage({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");
  const params = await searchParams;
  const code = typeof params.code === "string" ? params.code : null;
  const state = typeof params.state === "string" ? params.state : null;
  const handle = typeof params.handle === "string" ? params.handle : null;
  const toolkitConfigId =
    typeof params.toolkit_config_id === "string"
      ? params.toolkit_config_id
      : null;
  const error = typeof params.error === "string" ? params.error : null;

  const result: ExchangeResult =
    !error &&
    code != null &&
    state != null &&
    handle != null &&
    toolkitConfigId != null
      ? await exchangeOnce(handle, toolkitConfigId, code, state)
      : {
          success: false,
          message:
            error ?? "Missing code, state, handle, or toolkit config ID.",
        };

  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Title order={2}>{t("title")}</Title>
        <CallbackResult
          success={result.success}
          message={result.success ? null : result.message}
        />
      </Stack>
    </Container>
  );
}
