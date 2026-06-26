"use client";

/** Agent context inner view. */
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
import {
  SessionContextView,
  SessionRawEventsView,
  SessionSystemPromptView,
} from "@/features/chat/context/SessionContextView";
import { trpc } from "@/trpc/client";
import type { AgentChatInnerView } from "../containers/useAgentChatContainer";
import type { AgentResponse } from "@azents/public-client";

interface AgentContextViewProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  view: Exclude<AgentChatInnerView, "chat">;
}

export function AgentContextView({
  handle,
  agent,
  sessionId,
  view,
}: AgentContextViewProps): React.ReactElement {
  const t = useTranslations("chat.context");
  const systemPromptT = useTranslations("chat.context.systemPrompt");
  const rawEventsT = useTranslations("chat.context.rawEventsPage");
  const query = trpc.chat.getAgentSessionContext.useQuery({
    agentId: agent.id,
    sessionId,
    limit: 300,
  });
  const sessionPath = `/w/${handle}/agents/${agent.id}/sessions/${sessionId}`;
  const contextHref = `${sessionPath}?page=context`;

  return (
    <Box p="lg" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
      <Stack gap="md">
        {view === "system-prompt" && (
          <BackToContextLink
            href={contextHref}
            label={systemPromptT("backToContext")}
          />
        )}
        {view === "raw-events" && (
          <BackToContextLink
            href={contextHref}
            label={rawEventsT("backToContext")}
          />
        )}
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
        {query.data && view === "context" && (
          <SessionContextView
            context={query.data}
            systemPromptHref={`${sessionPath}?page=system-prompt`}
            rawEventsHref={`${sessionPath}?page=raw-events`}
          />
        )}
        {query.data && view === "system-prompt" && (
          <SessionSystemPromptView context={query.data} />
        )}
        {query.data && view === "raw-events" && (
          <SessionRawEventsView context={query.data} />
        )}
      </Stack>
    </Box>
  );
}

function BackToContextLink({
  href,
  label,
}: {
  href: string;
  label: string;
}): React.ReactElement {
  return (
    <Button
      component={Link}
      href={href}
      variant="subtle"
      leftSection={<IconArrowLeft size={rem(16)} />}
      style={{ alignSelf: "flex-start" }}
    >
      {label}
    </Button>
  );
}
