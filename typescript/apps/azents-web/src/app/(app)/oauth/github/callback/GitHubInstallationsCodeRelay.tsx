"use client";

/**
 * Callback client component for GitHub OAuth installation list fetch.
 *
 * Pass authorization code and state received after OAuth authentication
 * to parent window via postMessage and close popup automatically.
 */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

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
    const opener = window.opener as Window | null;
    if (opener) {
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
