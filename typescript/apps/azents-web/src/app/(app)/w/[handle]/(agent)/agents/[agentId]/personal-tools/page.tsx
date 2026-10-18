import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { parseOriginSession } from "@/features/personal-tools/navigation";
import { trpc } from "@/trpc/server";
import { PersonalToolsComposition } from "./PersonalToolsComposition";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string; agentId: string }>;
  searchParams: Promise<{ originSession?: string | string[] }>;
}): Promise<React.ReactElement> {
  const { handle, agentId } = await params;
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    const originSessionId = parseOriginSession(
      (await searchParams).originSession,
    );
    let authorizedSessionId: string | null = null;
    if (originSessionId !== null) {
      try {
        await trpc.chat.getAgentSession({
          agentId: agent.id,
          sessionId: originSessionId,
        });
        authorizedSessionId = originSessionId;
      } catch (error) {
        if (!(
          error instanceof TRPCError &&
          ["NOT_FOUND", "FORBIDDEN", "UNAUTHORIZED"].includes(error.code)
        )) {
          throw error;
        }
      }
    }
    return (
      <PersonalToolsComposition
        handle={handle}
        agent={agent}
        originSessionId={authorizedSessionId ?? void 0}
      />
    );
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
