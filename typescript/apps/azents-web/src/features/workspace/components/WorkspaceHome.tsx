"use client";

/** Workspace Home — team agents view. */

import {
  Alert,
  Box,
  Button,
  Center,
  Container,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconEye, IconPlus, IconSearch } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentTeamCard } from "./AgentTeamCard";
import styles from "./WorkspaceHome.module.css";
import { WorkspaceHomeStatsRow } from "./WorkspaceHomeStatsRow";
import type { WorkspaceHomeContainerOutput } from "../containers/useWorkspaceHomeContainer";
import type { EnrichedAgent } from "../types";

function matchesQuery(agent: EnrichedAgent, query: string): boolean {
  if (!query) {
    return true;
  }
  const q = query.toLowerCase();
  return (
    agent.name.toLowerCase().includes(q) ||
    (agent.description ?? "").toLowerCase().includes(q)
  );
}

interface EmptyProps {
  message: string;
}

function EmptyCard({ message }: EmptyProps): React.ReactElement {
  return (
    <Box p="xl" ta="center" className={styles.emptyCard}>
      <Text size="sm" className={styles.mutedText}>
        {message}
      </Text>
    </Box>
  );
}

export function WorkspaceHome(
  props: WorkspaceHomeContainerOutput,
): React.ReactElement {
  const {
    handle,
    state,
    query,
    onQueryChange,
    showDisabled,
    onShowDisabledChange,
    membersCount,
  } = props;

  const t = useTranslations("workspace.home");

  if (state.type === "LOADING") {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Container size="md" py="xl">
        <Alert color="red">{state.message}</Alert>
      </Container>
    );
  }

  const { agents, stats } = state;
  const disabledAgentsCount = agents.filter((a) => !a.enabled).length;
  const visibleAgents = agents.filter(
    (a) => (showDisabled || a.enabled) && matchesQuery(a, query),
  );
  const newAgentHref = `/w/${handle}/agents/new`;

  return (
    <Box className={styles.root}>
      <Box className={styles.header} pt="lg" px={{ base: "md", sm: "xl" }}>
        <Container size="xl" px={0}>
          <Group justify="space-between" align="flex-end" wrap="wrap" mb="md">
            <Stack gap={4}>
              <Text
                size="xs"
                className={styles.mutedText}
                tt="uppercase"
                style={{ letterSpacing: 1 }}
              >
                {t("eyebrow", { handle })}
              </Text>
              <Title order={2} style={{ letterSpacing: -0.3 }}>
                {t("title")}
              </Title>
              <Text size="sm" className={styles.mutedText}>
                {t("subtitle", {
                  members: membersCount,
                  agents: agents.length,
                })}
              </Text>
            </Stack>
            <Group gap="xs">
              <Button
                variant="default"
                leftSection={<IconEye size={14} />}
                disabled
                title={t("activityFeedSoon")}
              >
                {t("activityFeed")}
              </Button>
              <Button
                component={Link}
                href={newAgentHref}
                leftSection={<IconPlus size={14} />}
              >
                {t("newAgent")}
              </Button>
            </Group>
          </Group>
        </Container>
      </Box>

      <Container size="xl" py="lg" px={{ base: "md", sm: "xl" }}>
        <WorkspaceHomeStatsRow stats={stats} />

        <Group align="center" mb="md" wrap="wrap">
          <TextInput
            leftSection={<IconSearch size={14} />}
            value={query}
            onChange={(e) => onQueryChange(e.currentTarget.value)}
            placeholder={t("search.agents")}
            classNames={{ input: styles.searchInput }}
            style={{ flex: 1, maxWidth: 380 }}
          />
          {disabledAgentsCount > 0 && (
            <Switch
              size="sm"
              checked={showDisabled}
              onChange={(e) => onShowDisabledChange(e.currentTarget.checked)}
              label={t("showDisabled", { count: disabledAgentsCount })}
            />
          )}
        </Group>

        {visibleAgents.length === 0 ? (
          <EmptyCard
            message={
              query
                ? t("empty.search")
                : agents.length === 0
                  ? t("empty.agents")
                  : t("empty.agentsFiltered")
            }
          />
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
            {visibleAgents.map((agent) => (
              <AgentTeamCard key={agent.id} handle={handle} agent={agent} />
            ))}
          </SimpleGrid>
        )}
      </Container>
    </Box>
  );
}
