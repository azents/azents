"use client";

/** Send a GitHub installations authorization result to the opener. */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { isWindowMessageTarget } from "@/shared/lib/window-message-target";

interface GitHubInstallationsCodeRelayProps {
  code: string;
  state: string;
}

export function GitHubInstallationsCodeRelay({
  code,
  state,
}: GitHubInstallationsCodeRelayProps): React.ReactElement {
  const t = useTranslations("oauth");

  useEffect(() => {
    const opener: unknown = window.opener;
    if (isWindowMessageTarget(opener)) {
      opener.postMessage(
        {
          type: "azents-github-installations-code",
          code,
          state,
        },
        window.location.origin,
      );
      const timer = setTimeout(() => window.close(), 1500);
      return () => clearTimeout(timer);
    }
    return () => {};
  }, [code, state]);

  return (
    <Alert icon={<IconCheck size={24} />} color="green" variant="light">
      <Text>{t("callbackSuccess")}</Text>
    </Alert>
  );
}
