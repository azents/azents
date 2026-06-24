/**
 * GitHub OAuth / App Setup callback server component.
 *
 * Handles two callbacks:
 * 1. GitHub App Setup: installation_id → parent window
 * 2. Installation list OAuth: code + state → parent window (server validates state)
 */

import { Container, Stack, Title } from "@mantine/core";
import { getTranslations } from "next-intl/server";
import { GitHubAppInstallResult } from "./GitHubAppInstallResult";
import { GitHubInstallationsCodeRelay } from "./GitHubInstallationsCodeRelay";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | null>>;
}

export default async function OAuthGitHubCallbackPage({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");
  const params = await searchParams;

  const installationId =
    typeof params.installation_id === "string" ? params.installation_id : null;
  const code = typeof params.code === "string" ? params.code : null;
  const state = typeof params.state === "string" ? params.state : null;

  // GitHub App Setup callback — pass installation_id to parent window
  if (installationId) {
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="lg">
          <Title order={2}>{t("title")}</Title>
          <GitHubAppInstallResult installationId={installationId} />
        </Stack>
      </Container>
    );
  }

  // Installation list OAuth callback — pass code + state to parent window
  if (code && state) {
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="lg">
          <Title order={2}>{t("title")}</Title>
          <GitHubInstallationsCodeRelay code={code} state={state} />
        </Stack>
      </Container>
    );
  }

  // Missing parameters — show error
  const { CallbackResult } = await import("../../mcp/callback/CallbackResult");
  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Title order={2}>{t("title")}</Title>
        <CallbackResult success={false} message="Missing code or state." />
      </Stack>
    </Container>
  );
}
