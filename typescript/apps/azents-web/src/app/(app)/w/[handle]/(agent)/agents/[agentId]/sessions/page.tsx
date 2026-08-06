import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentSessionDirectoryPage } from "@/features/agents/AgentSessionDirectoryPage";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId } = await params;
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    return <AgentSessionDirectoryPage handle={handle} agent={agent} />;
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
