import { TRPCError } from "@trpc/server";
import { notFound, redirect } from "next/navigation";
import { AgentChatTabPage } from "@/features/agents/AgentChatTabPage";
import { AgentContextPage } from "@/features/agents/AgentContextPage";
import { AgentSubagentsPage } from "@/features/agents/AgentSubagentsPage";
import { trpc } from "@/trpc/server";
import type { AgentContextPageView } from "@/features/agents/AgentContextPage";

type SessionPageView = "chat" | "subagents" | AgentContextPageView;

function parsePageView(value?: string | string[]): SessionPageView {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (
    rawValue === "context" ||
    rawValue === "system-prompt" ||
    rawValue === "raw-events" ||
    rawValue === "subagents"
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
  const pageValue = Array.isArray(query.page) ? query.page[0] : query.page;
  if (pageValue === "projects") {
    redirect(`/w/${handle}/agents/${agentId}/sessions/${sessionId}`);
  }
  try {
    const [agent] = await Promise.all([
      trpc.agent.get({ handle, agentId }),
      trpc.chat.getAgentSession({ agentId, sessionId }),
    ]);
    const view = parsePageView(query.page);
    if (view === "subagents") {
      return (
        <AgentSubagentsPage
          handle={handle}
          agent={agent}
          sessionId={sessionId}
        />
      );
    }
    if (view !== "chat") {
      return (
        <AgentContextPage
          handle={handle}
          agent={agent}
          sessionId={sessionId}
          view={view}
        />
      );
    }
    return (
      <AgentChatTabPage handle={handle} agent={agent} sessionId={sessionId} />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
