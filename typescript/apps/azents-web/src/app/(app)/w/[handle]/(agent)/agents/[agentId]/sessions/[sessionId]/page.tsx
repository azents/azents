import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentChatTabPage } from "@/features/agents/AgentChatTabPage";
import { trpc } from "@/trpc/server";
import type { AgentChatInnerView } from "@/features/agents/containers/useAgentChatContainer";

function parseInnerView(value?: string | string[]): AgentChatInnerView {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (
    rawValue === "context" ||
    rawValue === "system-prompt" ||
    rawValue === "raw-events"
  ) {
    return rawValue;
  }
  return "chat";
}

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string; agentId: string; sessionId: string }>;
  searchParams: Promise<{ page?: string | string[] }>;
}): Promise<React.ReactElement> {
  const [{ handle, agentId, sessionId }, query] = await Promise.all([
    params,
    searchParams,
  ]);
  try {
    const [agent] = await Promise.all([
      trpc.agent.get({ handle, agentId }),
      trpc.chat.getAgentSession({ agentId, sessionId }),
    ]);
    return (
      <AgentChatTabPage
        handle={handle}
        agent={agent}
        sessionId={sessionId}
        view={parseInnerView(query.page)}
      />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
