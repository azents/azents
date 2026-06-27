import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentChatTabPage } from "@/features/agents/AgentChatTabPage";
import { AgentContextPage } from "@/features/agents/AgentContextPage";
import { AgentProjectsPage } from "@/features/agents/AgentProjectsPage";
import { trpc } from "@/trpc/server";
import type { AgentContextPageView } from "@/features/agents/AgentContextPage";

type SessionPageView = "chat" | "projects" | AgentContextPageView;

function parsePageView(value?: string | string[]): SessionPageView {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (rawValue === "projects") {
    return "projects";
  }
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
    const view = parsePageView(query.page);
    if (view === "projects") {
      return (
        <AgentProjectsPage
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
