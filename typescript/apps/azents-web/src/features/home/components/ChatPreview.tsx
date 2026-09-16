"use client";

/** Chat interface preview — agent team collaboration demo */
import { Box, Divider, Group, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";

/** Agent-related keys in chatPreview namespace */
type AgentNameKey = "contentWriter" | "socialManager" | "analytics" | "design";

type AgentMessageKey =
  | "contentWriterMessage"
  | "socialManagerMessage"
  | "analyticsMessage"
  | "designMessage";

/** Agent response data */
interface AgentResponse {
  nameKey: AgentNameKey;
  messageKey: AgentMessageKey;
  color: string;
}

/** Agent list (text is i18n and colors use theme tokens). */
const AGENTS: AgentResponse[] = [
  {
    nameKey: "contentWriter",
    messageKey: "contentWriterMessage",
    color: "var(--mantine-color-blue-6)",
  },
  {
    nameKey: "socialManager",
    messageKey: "socialManagerMessage",
    color: "var(--mantine-color-violet-6)",
  },
  {
    nameKey: "analytics",
    messageKey: "analyticsMessage",
    color: "var(--mantine-color-teal-6)",
  },
  {
    nameKey: "design",
    messageKey: "designMessage",
    color: "var(--mantine-color-orange-6)",
  },
];

export function ChatPreview(): React.ReactElement {
  const t = useTranslations("chatPreview");

  return (
    <Box
      style={{
        margin: "0 auto",
        width: "100%",
        maxWidth: rem(500),
        borderRadius: "var(--mantine-radius-lg)",
        border: `${rem(1)} solid var(--mantine-color-default-border)`,
        backgroundColor: "var(--mantine-color-default)",
        padding: rem(24),
      }}
    >
      <Stack gap="md">
        {/* Channel header */}
        <Text ff="monospace" c="dimmed" size="sm">
          {t("channel")}
        </Text>

        <Divider color="var(--mantine-color-default-border)" />

        {/* User message */}
        <Group gap="sm" align="flex-start">
          <Box
            style={{
              display: "flex",
              width: rem(32),
              height: rem(32),
              flexShrink: 0,
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "50%",
              backgroundColor: "var(--mantine-color-dark-4)",
            }}
          >
            <Text size="xs" fw={600}>
              JK
            </Text>
          </Box>
          <Text size="sm">{t("userMessage")}</Text>
        </Group>

        <Divider color="var(--mantine-color-default-border)" />

        {/* Agent response list */}
        <Stack gap="xs">
          {AGENTS.map((agent) => (
            <Group key={agent.nameKey} gap="sm" align="center">
              <Box
                style={{
                  width: rem(8),
                  height: rem(8),
                  flexShrink: 0,
                  borderRadius: "50%",
                  backgroundColor: agent.color,
                }}
              />
              <Text ff="monospace" size="xs" c={agent.color} fw={500}>
                {t(agent.nameKey)}
              </Text>
              <Text size="xs" c="dimmed">
                {t(agent.messageKey)}
              </Text>
            </Group>
          ))}
        </Stack>

        <Divider color="var(--mantine-color-default-border)" />

        {/* Summary bar */}
        <Text size="xs" c="teal">
          {t("summary")}
        </Text>
      </Stack>
    </Box>
  );
}
