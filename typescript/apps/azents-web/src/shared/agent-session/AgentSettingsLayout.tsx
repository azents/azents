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
  originSessionId?: string;
}

export function AgentSettingsLayout({
  handle,
  agent,
  backTarget,
  children,
  backMaxWidth = rem(960),
  originSessionId,
}: AgentSettingsLayoutProps): React.ReactElement {
  const t = useTranslations("workspace.agents.settingsLayout");
  const tChat = useTranslations("workspace.agents.detail");
  const settingsHref = `/w/${handle}/agents/${agent.id}/settings`;
  const backHref =
    backTarget === "agent" ? `/w/${handle}/agents/${agent.id}` : settingsHref;
  const backLabel =
    backTarget === "agent" ? t("backToAgent") : t("backToSettings");

  return (
    <SettingsPageLayout
      header={<AgentSettingsHeader agent={agent} />}
      backHref={
        originSessionId == null
          ? backHref
          : `/w/${encodeURIComponent(handle)}/agents/${encodeURIComponent(agent.id)}/sessions/${encodeURIComponent(originSessionId)}`
      }
      backLabel={originSessionId == null ? backLabel : tChat("tabs.chat")}
      backMaxWidth={backMaxWidth}
    >
      {children}
    </SettingsPageLayout>
  );
}
