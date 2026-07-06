"use client";

/**
 * Workspace Home top team stats 4-card.
 *
 * Design: active agents (enabled/total) / total agents.
 * "Currently working (busy)" omitted in first pass due to no realtime state tracking.
 */

import { SimpleGrid, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import styles from "./WorkspaceHome.module.css";
import type { WorkspaceHomeStats } from "../types";

interface StatCardProps {
  label: string;
  value: number;
  total?: number | null;
  subtitle?: string | null;
}

function StatCard({
  label,
  value,
  total,
  subtitle,
}: StatCardProps): React.ReactElement {
  return (
    <Stack gap={4} p="md" className={styles.statCard}>
      <Text
        size="xs"
        tt="uppercase"
        className={styles.statLabel}
        style={{ letterSpacing: 0.5 }}
      >
        {label}
      </Text>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <Text size="xl" fw={600}>
          {value}
        </Text>
        {total != null && (
          <Text size="sm" className={styles.statTotal}>
            / {total}
          </Text>
        )}
      </div>
      {subtitle != null && (
        <Text size="xs" className={styles.statSubtitle}>
          {subtitle}
        </Text>
      )}
    </Stack>
  );
}

interface WorkspaceHomeStatsRowProps {
  stats: WorkspaceHomeStats;
}

export function WorkspaceHomeStatsRow({
  stats,
}: WorkspaceHomeStatsRowProps): React.ReactElement {
  const t = useTranslations("workspace.home.stats");
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm" mb="lg">
      <StatCard
        label={t("activeAgents")}
        value={stats.enabledAgents}
        total={stats.totalAgents}
      />
      <StatCard label={t("totalAgents")} value={stats.totalAgents} />
    </SimpleGrid>
  );
}
