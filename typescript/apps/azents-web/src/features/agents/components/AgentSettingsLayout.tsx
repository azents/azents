"use client";

/** Shared layout for Agent settings pages. */

import { rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import { AgentSettingsHeader } from "@/shared/agent-session/AgentSettingsHeader";
import { SettingsPageLayout } from "@/shared/components/SettingsPageLayout";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsLayoutProps {
  handle: string;
  agent: AgentResponse;
  backTarget: "agent" | "settings";
  children: React.ReactNode;
  backMaxWidth?: string;
}

export function AgentSettingsLayout({
  handle,
  agent,
  backTarget,
  children,
  backMaxWidth = rem(960),
}: AgentSettingsLayoutProps): React.ReactElement {
  const t = useTranslations("workspace.agents.settingsLayout");
  const settingsHref = `/w/${handle}/agents/${agent.id}/settings`;
  const backHref =
    backTarget === "agent" ? `/w/${handle}/agents/${agent.id}` : settingsHref;
  const backLabel =
    backTarget === "agent" ? t("backToAgent") : t("backToSettings");

  return (
    <SettingsPageLayout
      header={<AgentSettingsHeader agent={agent} />}
      backHref={backHref}
      backLabel={backLabel}
      backMaxWidth={backMaxWidth}
    >
      {children}
    </SettingsPageLayout>
  );
}
