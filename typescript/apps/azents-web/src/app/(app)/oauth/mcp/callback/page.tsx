/**
 * MCP OAuth2 callback server component.
 *
 * Receives code/state from OAuth provider and requests token exchange to backend,
 * then passes the result to the feature page.
 *
 * authorization code is one-time-use, so React.cache prevents duplicate calls.
 */

import { TRPCError } from "@trpc/server";
import { cache } from "react";
import { OAuthMcpCallbackPage } from "@/features/toolkits/OAuthMcpCallbackPage";
import {
  decodeMcpCallbackTarget,
  mcpCallbackReturnPath,
} from "@/shared/toolkits/mcp-callback-target";
import { trpc } from "@/trpc/server";

type ExchangeResult = { success: true } | { success: false; message: string };

/** authorization code is one-time-use — prevent duplicate calls in same render cycle */
const exchangeOnce = cache(
  async (
    type: "personal" | "workload",
    handle: string | null,
    toolkitConfigId: string,
    agentId: string | null,
    code: string,
    state: string,
  ): Promise<ExchangeResult> => {
    try {
      if (handle == null) {
        throw new Error("MCP callback requires a Workspace handle.");
      }
      if (type === "personal") {
        await trpc.personalToolkit.exchangeOauth({
          handle,
          toolkitId: toolkitConfigId,
          code,
          state,
        });
      } else if (agentId == null) {
        await trpc.toolkit.oauthExchange({
          handle,
          toolkitConfigId,
          code,
          state,
        });
      } else {
        await trpc.toolkit.agentOauthExchange({
          handle,
          agentId,
          toolkitConfigId,
          code,
          state,
        });
      }
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

export default async function Page({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const params = await searchParams;
  const code = typeof params.code === "string" ? params.code : null;
  const state = typeof params.state === "string" ? params.state : null;
  const target = decodeMcpCallbackTarget(params);
  const error = typeof params.error === "string" ? params.error : null;

  const result: ExchangeResult =
    !error && code != null && state != null && target != null
      ? await exchangeOnce(
          target.type,
          target.handle,
          target.toolkitId,
          target.type === "workload" ? target.agentId : null,
          code,
          state,
        )
      : {
          success: false,
          message:
            error ??
            "Missing or invalid OAuth callback target, code, or state.",
        };

  return (
    <OAuthMcpCallbackPage
      success={result.success}
      message={result.success ? null : result.message}
      returnHref={target != null ? mcpCallbackReturnPath(target) : null}
    />
  );
}
