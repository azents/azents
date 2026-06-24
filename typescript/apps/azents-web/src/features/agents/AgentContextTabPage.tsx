"use client";

/** Agent Context tab page. */
import { Alert, Box, Center, Loader, rem, Stack, Text } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { SessionContextView } from "@/features/chat/context/SessionContextView";
import { trpc } from "@/trpc/client";
import { AgentHeader } from "./components/AgentHeader";
import type { AgentResponse } from "@azents/public-client";

interface AgentContextTabPageProps {
  handle: string;
  agent: AgentResponse;
}

export function AgentContextTabPage({
  handle,
  agent,
}: AgentContextTabPageProps): React.ReactElement {
  const t = useTranslations("chat.context");
  const query = trpc.chat.getAgentSessionContext.useQuery({
    agentId: agent.id,
    limit: 300,
  });

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentHeader handle={handle} agent={agent} />
      <Box p="lg" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {query.isLoading && (
          <Center h={240}>
            <Stack align="center" gap="sm">
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                {t("loading")}
              </Text>
            </Stack>
          </Center>
        )}
        {query.isError && (
          <Alert
            icon={<IconAlertCircle size={rem(16)} />}
            color="red"
            variant="light"
          >
            {t("loadError", { message: query.error.message })}
          </Alert>
        )}
        {query.data && (
          <SessionContextView
            context={query.data}
            systemPromptHref={`/w/${handle}/agents/${agent.id}/context/system-prompt`}
            rawEventsHref={`/w/${handle}/agents/${agent.id}/context/raw-events`}
          />
        )}
      </Box>
    </Box>
  );
}
