import { WorkspaceRuntimeExecutionPage } from "@/features/runtime-execution/WorkspaceRuntimeExecutionPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceRuntimeExecutionPage handle={handle} />;
}
