import "server-only";
import { TRPCError } from "@trpc/server";
import { trpc } from "@/trpc/server";
import { parsePersonalToolsOrigin } from "./navigation";
import type { PersonalToolsOrigin } from "./navigation";

export async function resolvePersonalToolsOrigin(
  query: Readonly<Record<string, unknown>>,
  handle: string,
): Promise<PersonalToolsOrigin | null> {
  const origin = parsePersonalToolsOrigin(query);
  if (origin === null || origin.handle !== handle) {
    return null;
  }
  try {
    const agent = await trpc.agent.get({
      handle: origin.handle,
      agentId: origin.agentId,
    });
    if (origin.sessionId != null) {
      await trpc.chat.getAgentSession({
        agentId: agent.id,
        sessionId: origin.sessionId,
      });
    }
    return {
      handle: origin.handle,
      agentId: agent.id,
      ...(origin.sessionId != null && { sessionId: origin.sessionId }),
    };
  } catch (error) {
    if (
      error instanceof TRPCError &&
      ["NOT_FOUND", "FORBIDDEN", "UNAUTHORIZED"].includes(error.code)
    ) {
      return null;
    }
    throw error;
  }
}
