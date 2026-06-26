import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentContextTabPage } from "@/features/agents/AgentContextTabPage";
import { trpc } from "@/trpc/server";

export default async function AgentContextRoot({
  params,
}: {
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId } = await params;
  let agent;
  try {
    agent = await trpc.agent.get({ handle, agentId });
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
  return <AgentContextTabPage handle={handle} agent={agent} />;
}
