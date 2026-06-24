/**
 * Workspace join request route
 *
 * Page for non-members to request joining workspace.
 */
import { WorkspaceJoinPage } from "@/features/workspace-join/pages/WorkspaceJoinPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceJoinPage handle={handle} />;
}
