"use client";

/** Shared layout for Agent settings pages. */

import { Box, Button, Group, rem } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentSettingsHeader } from "./AgentSettingsHeader";
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
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSettingsHeader agent={agent} />
      <Box
        style={{
          borderBottom: "0.0625rem solid var(--mantine-color-default-border)",
          backgroundColor: "var(--mantine-color-body)",
        }}
      >
        <Group px="md" py="xs" maw={backMaxWidth} mx="auto" w="100%">
          <Button
            component={Link}
            href={backHref}
            variant="subtle"
            leftSection={<IconArrowLeft size={rem(16)} />}
          >
            {backLabel}
          </Button>
        </Group>
      </Box>
      {children}
    </Box>
  );
}
