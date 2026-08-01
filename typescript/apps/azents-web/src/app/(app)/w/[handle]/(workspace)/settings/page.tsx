/** Workspace settings overview route. */

import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { WorkspaceSettingsHubPage } from "@/features/workspace-settings/WorkspaceSettingsHubPage";
import { trpc } from "@/trpc/server";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  try {
    const workspace = await trpc.workspace.get({ handle });
    return <WorkspaceSettingsHubPage workspace={workspace} />;
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
