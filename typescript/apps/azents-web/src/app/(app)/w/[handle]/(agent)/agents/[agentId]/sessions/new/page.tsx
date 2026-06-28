import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentDraftChatPage } from "@/features/agents/AgentDraftChatPage";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId } = await params;
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    return <AgentDraftChatPage handle={handle} agent={agent} />;
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
