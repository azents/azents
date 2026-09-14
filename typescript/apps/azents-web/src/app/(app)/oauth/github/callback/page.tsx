/**
 * GitHub OAuth / App Setup callback server component.
 *
 * Handles two callbacks:
 * 1. GitHub App Setup: installation_id → parent window
 * 2. Installation list OAuth: code + state → parent window (server validates state)
 */

import { GitHubOAuthCallbackPage } from "@/features/toolkits/GitHubOAuthCallbackPage";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | null>>;
}

export default async function Page({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const params = await searchParams;

  const installationId =
    typeof params.installation_id === "string" ? params.installation_id : null;
  const code = typeof params.code === "string" ? params.code : null;
  const state = typeof params.state === "string" ? params.state : null;

  return (
    <GitHubOAuthCallbackPage
      installationId={installationId}
      code={code}
      state={state}
    />
  );
}
