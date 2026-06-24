/**
 * Workspace home route — "Our team agents" view.
 */
import { WorkspaceHomePage } from "@/features/workspace/pages/WorkspaceHomePage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <WorkspaceHomePage handle={handle} />;
}
