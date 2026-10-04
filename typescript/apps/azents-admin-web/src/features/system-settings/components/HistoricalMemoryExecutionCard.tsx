"use client";

import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { IconBrain } from "@tabler/icons-react";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useHistoricalMemoryExecutionCardContainer } from "../containers/useHistoricalMemoryExecutionCardContainer";
import { isPositiveInteger } from "../historical-memory-execution-state";
import type { HistoricalMemoryExecutionCardProps } from "../containers/useHistoricalMemoryExecutionCardContainer";

function HistoricalMemoryExecutionCardContent({
  state,
  draft,
  dirty,
  saving,
  saveDisabled,
  mutationError,
  conflict,
  reloading,
  onMaxTurnsChange,
  onTimeoutSecondsChange,
  onSave,
  onReload,
}: HistoricalMemoryExecutionCardProps): React.ReactElement {
  let content: React.ReactNode;
  switch (state.type) {
    case "LOADING":
      content = <Loader size="sm" />;
      break;
    case "ERROR":
      content = (
        <Alert color="red" title="Unable to load Historical Memory execution">
          <Stack gap="sm">
            <Text size="sm">{state.message}</Text>
            <Button variant="light" loading={reloading} onClick={onReload}>
              Try again
            </Button>
          </Stack>
        </Alert>
      );
      break;
    case "LOADED":
      content = (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
            <NumberInput
              label="Maximum turns"
              description="Leave blank for unlimited turns."
              placeholder="Unlimited"
              value={draft.maxTurns}
              min={1}
              allowDecimal={false}
              allowNegative={false}
              disabled={saving}
              error={
                draft.maxTurns !== "" && !isPositiveInteger(draft.maxTurns)
                  ? "Enter a positive whole number or leave blank."
                  : false
              }
              onChange={onMaxTurnsChange}
            />
            <NumberInput
              label="Timeout"
              description="Execution timeout in seconds. Default: 600 seconds."
              value={draft.timeoutSeconds}
              min={1}
              allowDecimal={false}
              allowNegative={false}
              suffix=" seconds"
              disabled={saving}
              error={
                !isPositiveInteger(draft.timeoutSeconds)
                  ? "Enter a positive whole number."
                  : false
              }
              onChange={onTimeoutSecondsChange}
            />
          </SimpleGrid>
          <Divider />
          <Group justify="space-between" align="flex-end">
            <Text size="xs" c="dimmed">
              Save applies the execution limits to new Historical Memory work.
            </Text>
            <Button loading={saving} disabled={saveDisabled} onClick={onSave}>
              Save execution settings
            </Button>
          </Group>
        </>
      );
      break;
  }

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="lg">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <IconBrain size={20} />
              <Text fw={700}>Historical Memory execution</Text>
            </Group>
            <Text size="sm" c="dimmed">
              Control instance-wide turn and timeout limits for Historical
              Memory.
            </Text>
          </Stack>
          <Group gap="xs">
            {dirty && (
              <Badge color="yellow" variant="light">
                Unsaved changes
              </Badge>
            )}
            {state.type === "LOADED" && (
              <Badge variant="light">
                Version {state.detail.admin_version}
              </Badge>
            )}
          </Group>
        </Group>
        {mutationError && (
          <Alert
            color="red"
            title={
              conflict
                ? "Settings changed before this save"
                : "Unable to save Historical Memory execution"
            }
          >
            <Stack gap="sm">
              <Text size="sm">{mutationError}</Text>
              {conflict && (
                <>
                  <Text size="sm">
                    Reload the latest settings, then reapply your changes.
                  </Text>
                  <Button
                    variant="light"
                    loading={reloading}
                    onClick={onReload}
                  >
                    Reload latest settings
                  </Button>
                </>
              )}
            </Stack>
          </Alert>
        )}
        {content}
      </Stack>
    </Paper>
  );
}

export const HistoricalMemoryExecutionCard = createReactContainer(
  "HistoricalMemoryExecutionCard",
  useHistoricalMemoryExecutionCardContainer,
  HistoricalMemoryExecutionCardContent,
);
