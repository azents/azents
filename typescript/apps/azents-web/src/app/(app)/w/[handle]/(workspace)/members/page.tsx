/**
 * Workspace member management route
 */
import { WorkspaceMembers } from "@/features/workspace/pages/WorkspaceMembers";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceMembers handle={handle} />;
}
