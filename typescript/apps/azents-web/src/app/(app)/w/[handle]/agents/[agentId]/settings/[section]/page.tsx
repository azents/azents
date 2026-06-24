import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentSettingsTabPage } from "@/features/agents/AgentSettingsTabPage";
import { trpc } from "@/trpc/server";

export default async function AgentSettingsSectionPage({
  params,
}: {
  params: Promise<{ handle: string; agentId: string; section: string }>;
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
  return <AgentSettingsTabPage handle={handle} agent={agent} />;
}
