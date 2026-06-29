import { redirect } from "next/navigation";

export default async function AgentDetailIndex({
  params,
}: {
  params: Promise<{ handle: string; agentId: string }>;
}): Promise<never> {
  const { handle, agentId } = await params;
  redirect(`/w/${handle}/agents/${agentId}/sessions/new`);
}
