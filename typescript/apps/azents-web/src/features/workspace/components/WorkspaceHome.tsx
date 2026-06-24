"use client";

/**
 * Workspace Home — "Our team agents" view.
 *
 * Port of design M1P3PGa_LxPQZVVCJmKvPg home.jsx.
 *  - Header (white) + underline tabs (Agents / Subagents / All) + count pill
 *  - Two buttons: "Activity feed" (placeholder) + "New agent"
 *  - Body (beige): team stats + search + grid/list + same bg in empty space
 */

import {
  Alert,
  Box,
  Button,
  Center,
  Container,
  Divider,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconEye, IconPlus, IconSearch } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentTeamCard } from "./AgentTeamCard";
import { SubagentTeamRow } from "./SubagentTeamRow";
import styles from "./WorkspaceHome.module.css";
import { WorkspaceHomeStatsRow } from "./WorkspaceHomeStatsRow";
import type { WorkspaceHomeContainerOutput } from "../containers/useWorkspaceHomeContainer";
import type { AgentTeamFilter, EnrichedAgent } from "../types";

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

interface SectionHeaderProps {
  title: string;
  subtitle: string;
  count: number;
}

function SectionHeader({
  title,
  subtitle,
  count,
}: SectionHeaderProps): React.ReactElement {
  return (
    <Group gap="sm" mb="sm" align="baseline">
      <Text fw={600}>{title}</Text>
      <Text size="xs" px="xs" className={styles.sectionCount}>
        {count}
      </Text>
      <Text size="xs" className={styles.mutedText}>
        {subtitle}
      </Text>
    </Group>
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

/** Custom underline tab — reproduces design layout. */
interface TabItem {
  value: AgentTeamFilter;
  label: string;
  count: number;
}

interface HomeTabsProps {
  value: AgentTeamFilter;
  onChange: (value: AgentTeamFilter) => void;
  tabs: TabItem[];
}

function HomeTabs({
  value,
  onChange,
  tabs,
}: HomeTabsProps): React.ReactElement {
  return (
    <Group gap="2xs" wrap="nowrap" className={styles.tabs}>
      {tabs.map((t) => {
        const active = t.value === value;
        return (
          <UnstyledButton
            key={t.value}
            onClick={() => onChange(t.value)}
            px="sm"
            py="xs"
            className={styles.tabButton}
            data-active={active}
          >
            {t.label}
            <Text span size="xs" px="2xs" className={styles.tabCount}>
              {t.count}
            </Text>
          </UnstyledButton>
        );
      })}
    </Group>
  );
}

export function WorkspaceHome(
  props: WorkspaceHomeContainerOutput,
): React.ReactElement {
  const {
    handle,
    state,
    view,
    onViewChange,
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

  const { primaryAgents, subagents, stats } = state;

  const tabs: TabItem[] = [
    {
      value: "agents",
      label: t("filter.agents"),
      count: primaryAgents.length,
    },
    {
      value: "subagents",
      label: t("filter.subagents"),
      count: subagents.length,
    },
    {
      value: "all",
      label: t("filter.all"),
      count: primaryAgents.length + subagents.length,
    },
  ];

  const disabledPrimaryCount = primaryAgents.filter((a) => !a.enabled).length;

  const visiblePrimary = primaryAgents.filter(
    (a) => (showDisabled || a.enabled) && matchesQuery(a, query),
  );
  const visibleSubs = subagents.filter(
    (a) => (showDisabled || a.enabled) && matchesQuery(a, query),
  );

  const newAgentHref = `/w/${handle}/agents/new`;

  return (
    <Box className={styles.root}>
      {/* Page header — mode-specific raised surface */}
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
                  agents: primaryAgents.length,
                  subagents: subagents.length,
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
          <HomeTabs value={view} onChange={onViewChange} tabs={tabs} />
        </Container>
      </Box>

      {/* Body — beige background (owned by root), same bg through empty space */}
      <Container size="xl" py="lg" px={{ base: "md", sm: "xl" }}>
        <WorkspaceHomeStatsRow stats={stats} />

        <Group align="center" mb="md" wrap="wrap">
          <TextInput
            leftSection={<IconSearch size={14} />}
            value={query}
            onChange={(e) => onQueryChange(e.currentTarget.value)}
            placeholder={
              view === "subagents" ? t("search.subagents") : t("search.agents")
            }
            classNames={{ input: styles.searchInput }}
            style={{ flex: 1, maxWidth: 380 }}
          />
          {disabledPrimaryCount > 0 &&
            (view === "agents" || view === "all") && (
              <Switch
                size="sm"
                checked={showDisabled}
                onChange={(e) => onShowDisabledChange(e.currentTarget.checked)}
                label={t("showDisabled", { count: disabledPrimaryCount })}
              />
            )}
        </Group>

        {(view === "agents" || view === "all") && (
          <Box mb={view === "all" ? "xl" : 0}>
            {view === "all" && (
              <SectionHeader
                title={t("sections.agents.title")}
                subtitle={t("sections.agents.subtitle")}
                count={visiblePrimary.length}
              />
            )}
            {visiblePrimary.length === 0 ? (
              <EmptyCard
                message={
                  query
                    ? t("empty.search")
                    : primaryAgents.length === 0
                      ? t("empty.agents")
                      : t("empty.agentsFiltered")
                }
              />
            ) : (
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
                {visiblePrimary.map((agent) => (
                  <AgentTeamCard key={agent.id} handle={handle} agent={agent} />
                ))}
              </SimpleGrid>
            )}
          </Box>
        )}

        {view === "all" &&
          visiblePrimary.length > 0 &&
          visibleSubs.length > 0 && <Divider my="lg" />}

        {(view === "subagents" || view === "all") && (
          <Box>
            {view === "all" && (
              <SectionHeader
                title={t("sections.subagents.title")}
                subtitle={t("sections.subagents.subtitle")}
                count={visibleSubs.length}
              />
            )}
            {view === "subagents" && (
              <Alert
                color="blue"
                variant="light"
                mb="md"
                className={styles.noticeAlert}
              >
                {t("sections.subagents.notice")}
              </Alert>
            )}
            {visibleSubs.length === 0 ? (
              <EmptyCard
                message={
                  query
                    ? t("empty.search")
                    : subagents.length === 0
                      ? t("empty.subagents")
                      : t("empty.subagentsFiltered")
                }
              />
            ) : (
              <Stack gap="xs">
                {visibleSubs.map((sa) => (
                  <SubagentTeamRow key={sa.id} handle={handle} subagent={sa} />
                ))}
              </Stack>
            )}
          </Box>
        )}
      </Container>
    </Box>
  );
}
