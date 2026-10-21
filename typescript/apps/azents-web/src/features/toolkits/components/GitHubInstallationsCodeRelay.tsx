"use client";

/** Send a GitHub installations authorization result to the opener. */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useGitHubInstallationsCodeRelayController } from "../containers/useGitHubResultControllers";

export const GitHubInstallationsCodeRelay = createReactContainer(
  "GitHubInstallationsCodeRelay",
  useGitHubInstallationsCodeRelayController,
  GitHubInstallationsCodeRelayView,
);

export function GitHubInstallationsCodeRelayView(): React.ReactElement {
  const t = useTranslations("oauth");

  return (
    <Alert icon={<IconCheck size={24} />} color="green" variant="light">
      <Text>{t("callbackSuccess")}</Text>
    </Alert>
  );
}
