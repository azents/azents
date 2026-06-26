import { AgentFormPage } from "@/features/agents/AgentFormPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <AgentFormPage handle={handle} />;
}
