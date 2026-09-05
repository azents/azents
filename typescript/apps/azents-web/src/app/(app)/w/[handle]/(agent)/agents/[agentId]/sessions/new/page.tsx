import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentDraftChatPage } from "@/features/chat/AgentDraftChatPage";
import { trpc } from "@/trpc/server";
import type { AgentDraftSessionScope } from "@/features/chat/containers/useAgentDraftChatContainer";

function parseSessionScope(value?: string | string[]): AgentDraftSessionScope {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === "user") {
    return "user";
  }
  return "team";
}

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string; agentId: string }>;
  searchParams: Promise<{ scope?: string | string[] }>;
}): Promise<React.ReactElement> {
  const [{ handle, agentId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  const sessionScope = parseSessionScope(query.scope);
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    return (
      <AgentDraftChatPage
        handle={handle}
        agent={agent}
        sessionScope={sessionScope}
      />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
