"use client";

/** Workspace identity header for Workspace settings pages. */

import { Box, Group, rem, Stack, Text, ThemeIcon } from "@mantine/core";
import { IconBuilding } from "@tabler/icons-react";
import type { WorkspaceResponse } from "@azents/public-client";

interface WorkspaceSettingsHeaderProps {
  workspace: WorkspaceResponse;
}

export function WorkspaceSettingsHeader({
  workspace,
}: WorkspaceSettingsHeaderProps): React.ReactElement {
  return (
    <Box
      style={{
        borderBottom: "0.0625rem solid var(--mantine-color-default-border)",
        backgroundColor: "var(--mantine-color-body)",
      }}
    >
      <Group align="center" gap="md" px="lg" py="sm" wrap="nowrap">
        <ThemeIcon variant="light" size={rem(40)} radius="xl">
          <IconBuilding size={rem(20)} />
        </ThemeIcon>
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} size="md" truncate>
            {workspace.name}
          </Text>
          <Text size="xs" c="dimmed" truncate>
            @{workspace.handle}
          </Text>
        </Stack>
      </Group>
    </Box>
  );
}
