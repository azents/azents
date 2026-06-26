import { TRPCError } from "@trpc/server";
import { notFound, redirect } from "next/navigation";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<never> {
  const { handle, agentId } = await params;
  try {
    await trpc.agent.get({ handle, agentId });
    const session = await trpc.chat.getTeamPrimaryAgentSession({ agentId });
    redirect(`/w/${handle}/agents/${agentId}/sessions/${session.id}`);
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
