"use client";

/** Agent raw event inspector page. */
import {
  Alert,
  Box,
  Button,
  Center,
  Loader,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { IconAlertCircle, IconArrowLeft } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { SessionRawEventsView } from "@/features/chat/context/SessionContextView";
import { trpc } from "@/trpc/client";
import { AgentHeader } from "./components/AgentHeader";
import type { AgentResponse } from "@azents/public-client";

interface AgentRawEventsPageProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
}

export function AgentRawEventsPage({
  handle,
  agent,
  sessionId,
}: AgentRawEventsPageProps): React.ReactElement {
  const t = useTranslations("chat.context");
  const rawEventsT = useTranslations("chat.context.rawEventsPage");
  const query = trpc.chat.getAgentSessionContext.useQuery({
    agentId: agent.id,
    sessionId,
    limit: 300,
  });
  const contextPath = `/w/${handle}/agents/${agent.id}/sessions/${sessionId}/context`;

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentHeader handle={handle} agent={agent} />
      <Box p="lg" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        <Stack gap="md">
          <Button
            component={Link}
            href={contextPath}
            variant="subtle"
            leftSection={<IconArrowLeft size={rem(16)} />}
            style={{ alignSelf: "flex-start" }}
          >
            {rawEventsT("backToContext")}
          </Button>
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
          {query.data && <SessionRawEventsView context={query.data} />}
        </Stack>
      </Box>
    </Box>
  );
}
