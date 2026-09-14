"use client";

/** Send the GitHub App installation ID to the opener and render success. */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";

interface GitHubAppInstallResultProps {
  installationId: string;
}

export function GitHubAppInstallResult({
  installationId,
}: GitHubAppInstallResultProps): React.ReactElement {
  const t = useTranslations("oauth");

  useEffect(() => {
    const opener: unknown = window.opener;
    if (isWindowMessageTarget(opener)) {
      opener.postMessage(
        {
          type: "azents-github-app-installed",
          installation_id: installationId,
        },
        window.location.origin,
      );
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
