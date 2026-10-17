"use client";

import { Card, Group, rem, SimpleGrid, Stack, Text } from "@mantine/core";
import { ToolkitTypeIcon } from "./ToolkitTypeIcon";
import type { ReactElement, ReactNode } from "react";

/** Presentation only: callers retain ownership, authorization and mutation state. */
export interface ToolkitCardProps {
  name: string;
  toolkitType: string;
  providerName?: string;
  description?: string | null;
  badges: ReactNode;
  actions: ReactNode;
  control?: ReactNode;
}

export function ToolkitCard({
  name,
  toolkitType,
  providerName,
  description,
  badges,
  actions,
  control,
}: ToolkitCardProps): ReactElement {
  return (
    <Card
      component="article"
      aria-label={name}
      withBorder
      radius="md"
      padding="lg"
      h="100%"
      style={{
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        gap: "var(--mantine-spacing-sm)",
      }}
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap="xs" style={{ minWidth: 0 }}>
          <ToolkitTypeIcon toolkitType={toolkitType} />
          <Text size="xs" c="dimmed">
            {providerName ?? toolkitType}
          </Text>
          <Text fw={600} style={{ overflowWrap: "anywhere" }}>
            {name}
          </Text>
          {description && (
            <Text size="sm" c="dimmed" style={{ overflowWrap: "anywhere" }}>
              {description}
            </Text>
          )}
        </Stack>
        {control}
      </Group>
      {badges}
      <Group
        justify="flex-end"
        gap="xs"
        mt="auto"
        pt="sm"
        style={{
          borderTop: `${rem(1)} solid var(--mantine-color-default-border)`,
        }}
      >
        {actions}
      </Group>
    </Card>
  );
}

export function ToolkitCollection({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
      {children}
    </SimpleGrid>
  );
}
