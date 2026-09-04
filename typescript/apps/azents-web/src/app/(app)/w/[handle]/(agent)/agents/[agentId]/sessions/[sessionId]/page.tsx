import { TRPCError } from "@trpc/server";
import { notFound, redirect } from "next/navigation";
import { AgentContextPage } from "@/features/agents/AgentContextPage";
import { AgentSubagentsPage } from "@/features/agents/AgentSubagentsPage";
import { AgentChatTabPage } from "@/features/chat/AgentChatTabPage";
import { ScheduledTasksPage } from "@/features/scheduled-tasks/ScheduledTasksPage";
import { SessionChannelsPage } from "@/features/session-channels/SessionChannelsPage";
import { trpc } from "@/trpc/server";
import type { AgentContextPageView } from "@/features/agents/AgentContextPage";

type SessionPageView =
  "chat" | "subagents" | "channels" | "scheduled-tasks" | AgentContextPageView;

function parsePageView(value?: string | string[]): SessionPageView {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (
    rawValue === "context" ||
    rawValue === "system-prompt" ||
    rawValue === "raw-events" ||
    rawValue === "subagents" ||
    rawValue === "channels" ||
    rawValue === "scheduled-tasks"
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
  searchParams: Promise<{
    page?: string | string[];
    taskId?: string | string[];
    edit?: string | string[];
  }>;
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
    const [agent, session] = await Promise.all([
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
          session={session}
        />
      );
    }
    if (view === "channels") {
      return (
        <SessionChannelsPage
          handle={handle}
          agent={agent}
          sessionId={sessionId}
          session={session}
        />
      );
    }
    if (view === "scheduled-tasks") {
      const taskId = Array.isArray(query.taskId)
        ? (query.taskId[0] ?? null)
        : (query.taskId ?? null);
      const edit = Array.isArray(query.edit) ? query.edit[0] : query.edit;
      return (
        <ScheduledTasksPage
          handle={handle}
          agent={agent}
          sessionId={sessionId}
          session={session}
          initialTaskId={taskId}
          openInitialTaskForEdit={edit === "1" && taskId !== null}
        />
      );
    }
    if (view !== "chat") {
      return (
        <AgentContextPage
          handle={handle}
          agent={agent}
          sessionId={sessionId}
          session={session}
          view={view}
        />
      );
    }
    return (
      <AgentChatTabPage
        handle={handle}
        agent={agent}
        sessionId={sessionId}
        session={session}
      />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
