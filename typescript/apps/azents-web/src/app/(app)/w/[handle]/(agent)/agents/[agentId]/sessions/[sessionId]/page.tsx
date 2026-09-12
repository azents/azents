import { TRPCError } from "@trpc/server";
import { notFound, redirect } from "next/navigation";
import { AgentChatTabPage } from "@/features/chat/AgentChatTabPage";
import { trpc } from "@/trpc/server";

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
