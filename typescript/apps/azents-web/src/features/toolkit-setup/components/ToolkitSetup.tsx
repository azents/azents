"use client";

/**
 * Toolkit setup redirect UI component.
 *
 * Shows loading state while redirecting to OAuth authorization URL,
 * and shows error message on failure.
 */

import { Alert, Container, Loader, Stack, Text } from "@mantine/core";
import { IconX } from "@tabler/icons-react";
import type { ToolkitSetupContainerOutput } from "../containers/useToolkitSetupContainer";

export function ToolkitSetup({
  state,
}: ToolkitSetupContainerOutput): React.ReactElement {
  if (state.type === "ERROR") {
    return (
      <Container size="xs" py="xl">
        <Stack align="center" gap="md">
          <Alert icon={<IconX size={16} />} color="red" w="100%">
            {state.message}
          </Alert>
        </Stack>
      </Container>
    );
  }

  return (
    <Container size="xs" py="xl">
      <Stack align="center" gap="lg">
        <Loader size="lg" />
        <Text c="dimmed">Redirecting to setup...</Text>
      </Stack>
    </Container>
  );
}
