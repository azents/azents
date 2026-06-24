"use client";

/**
 * GitHub App installation completion result client component.
 *
 * Pass installation_id received by callback after GitHub App installation
 * to window.opener via postMessage and render success UI.
 */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

interface GitHubAppInstallResultProps {
  installationId: string;
}

export function GitHubAppInstallResult({
  installationId,
}: GitHubAppInstallResultProps): React.ReactElement {
  const t = useTranslations("oauth");

  useEffect(() => {
    const opener = window.opener as Window | null;
    if (opener) {
      opener.postMessage(
        {
          type: "azents-github-app-installed",
          installation_id: installationId,
        },
        window.location.origin,
      );
      // Auto-close popup after message delivery
      const timer = setTimeout(() => window.close(), 1500);
      return () => clearTimeout(timer);
    }
    return () => {};
  }, [installationId]);

  return (
    <Alert icon={<IconCheck size={24} />} color="green" variant="light">
      <Text>{t("githubAppInstalled")}</Text>
    </Alert>
  );
}
