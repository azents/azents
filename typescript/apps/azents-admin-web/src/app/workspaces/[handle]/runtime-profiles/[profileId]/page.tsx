import { WorkspaceRuntimeProfileAdminPage } from "@/features/workspaces/WorkspaceRuntimeProfileAdminPage";

interface PageProps {
  params: Promise<{
    handle: string;
    profileId: string;
  }>;
}

export default async function Page({
  params,
}: PageProps): Promise<React.ReactElement> {
  const { handle, profileId } = await params;
  return (
    <WorkspaceRuntimeProfileAdminPage
      workspaceHandle={handle}
      profileId={profileId}
    />
  );
}
