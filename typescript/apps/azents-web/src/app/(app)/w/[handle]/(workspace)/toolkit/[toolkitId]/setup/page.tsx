/**
 * Toolkit OAuth setup redirect page route.
 *
 * /w/{handle}/toolkit/{toolkitId}/setup → redirects to toolkit OAuth auth URL.
 * To bypass external provider button URL length limits,
 * create button with short web app URL and start OAuth flow on this page.
 */
import { ToolkitSetupPage } from "@/features/toolkit-setup/ToolkitSetupPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; toolkitId: string }>;
}): Promise<React.ReactElement> {
  const { handle, toolkitId } = await params;
  return <ToolkitSetupPage handle={handle} toolkitId={toolkitId} />;
}
