import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentChatTabPage } from "@/features/agents/AgentChatTabPage";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; agentId: string; sessionId: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId, sessionId } = await params;
  try {
    const [agent] = await Promise.all([
      trpc.agent.get({ handle, agentId }),
      trpc.chat.getAgentSession({ agentId, sessionId }),
    ]);
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
