"use client";

/** Send the GitHub App installation ID to the opener and render success. */

import { Alert, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useGitHubAppInstallResultController } from "../containers/useGitHubResultControllers";

export const GitHubAppInstallResult = createReactContainer(
  "GitHubAppInstallResult",
  useGitHubAppInstallResultController,
  GitHubAppInstallResultView,
);

export function GitHubAppInstallResultView(): React.ReactElement {
  const t = useTranslations("oauth");

  return (
    <Alert icon={<IconCheck size={24} />} color="green" variant="light">
      <Text>{t("githubAppInstalled")}</Text>
    </Alert>
  );
}
