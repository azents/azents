/**
 * GitHub PAT settings page.
 *
 * URL: /w/{handle}/settings/github-pat
 */

import { GitHubPATSetupPage } from "@/features/github-pat-settings/GitHubPATSetupPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <GitHubPATSetupPage handle={handle} />;
}
