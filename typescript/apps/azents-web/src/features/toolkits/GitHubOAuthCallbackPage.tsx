import { Container, Stack, Title } from "@mantine/core";
import { getTranslations } from "next-intl/server";
import { GitHubAppInstallResult } from "./components/GitHubAppInstallResult";
import { GitHubInstallationsCodeRelay } from "./components/GitHubInstallationsCodeRelay";
import { OAuthMcpCallbackResult } from "./components/OAuthMcpCallbackResult";

interface GitHubOAuthCallbackPageProps {
  installationId: string | null;
  code: string | null;
  state: string | null;
}

export async function GitHubOAuthCallbackPage({
  installationId,
  code,
  state,
}: GitHubOAuthCallbackPageProps): Promise<React.ReactElement> {
  const t = await getTranslations("oauth");

  let content: React.ReactElement;
  if (installationId !== null) {
    content = <GitHubAppInstallResult installationId={installationId} />;
  } else if (code !== null && state !== null) {
    content = <GitHubInstallationsCodeRelay code={code} state={state} />;
  } else {
    content = (
      <OAuthMcpCallbackResult
        success={false}
        message="Missing code or state."
        returnHref={null}
      />
    );
  }

  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Title order={2}>{t("title")}</Title>
        {content}
      </Stack>
    </Container>
  );
}
