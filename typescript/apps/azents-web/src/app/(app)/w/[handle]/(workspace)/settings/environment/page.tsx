import { WorkspaceEnvironmentPage } from "@/features/workspace-settings/WorkspaceEnvironmentPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceEnvironmentPage handle={handle} />;
}
