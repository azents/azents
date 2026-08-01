"use client";

/** Workspace-domain wrapper around the shared settings page layout. */

import { rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import { SettingsPageLayout } from "@/shared/components/SettingsPageLayout";
import { WorkspaceSettingsHeader } from "./WorkspaceSettingsHeader";
import type { WorkspaceResponse } from "@azents/public-client";

interface WorkspaceSettingsLayoutProps {
  workspace: WorkspaceResponse;
  backTarget: "workspace" | "settings";
  children: React.ReactNode;
  backMaxWidth?: string;
}

export function WorkspaceSettingsLayout({
  workspace,
  backTarget,
  children,
  backMaxWidth = rem(960),
}: WorkspaceSettingsLayoutProps): React.ReactElement {
  const t = useTranslations("workspace.settings.layout");
  const workspaceHref = `/w/${workspace.handle}`;
  const settingsHref = `${workspaceHref}/settings`;
  const backHref = backTarget === "workspace" ? workspaceHref : settingsHref;
  const backLabel =
    backTarget === "workspace" ? t("backToWorkspace") : t("backToSettings");

  return (
    <SettingsPageLayout
      header={<WorkspaceSettingsHeader workspace={workspace} />}
      backHref={backHref}
      backLabel={backLabel}
      backMaxWidth={backMaxWidth}
    >
      {children}
    </SettingsPageLayout>
  );
}
