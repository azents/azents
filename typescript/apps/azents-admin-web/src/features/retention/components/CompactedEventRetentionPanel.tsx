"use client";

import {
  Alert,
  Button,
  Group,
  NumberInput,
  Paper,
  Stack,
  Switch,
  Text,
} from "@mantine/core";
import type { CompactedEventRetentionProps } from "../containers/useRetentionPageContainer";

export function CompactedEventRetentionPanel({
  retentionDays,
  saving,
  saveDisabled,
  errorMessage,
  onChange,
  onSave,
}: CompactedEventRetentionProps): React.ReactElement {
  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Stack gap={4}>
          <Text fw={700}>Compacted-event retention</Text>
          <Text size="sm" c="dimmed">
            Retain original history after compaction moves it out of the current
            context. This policy is separate from archived-session retention.
            The current summary and later events are preserved.
          </Text>
        </Stack>
        <Switch
          label="Unlimited compacted-event retention"
          description="Default: preserve original history without automatic expiration."
          checked={retentionDays === null}
          onChange={(event) =>
            onChange(event.currentTarget.checked ? null : 60)
          }
        />
        <NumberInput
          label="Compacted-event retention days"
          description="Whole days since the event first moved behind the compaction head. Later compaction does not restart this period."
          min={0}
          max={2_147_483_647}
          allowDecimal={false}
          value={retentionDays ?? ""}
          disabled={retentionDays === null || saving}
          onChange={(value) => {
            if (typeof value === "number") {
              onChange(value);
            }
          }}
        />
        {retentionDays !== null && (
          <Alert
            color="orange"
            title="Expired original history is permanently deleted"
          >
            Applies to existing and future compacted events. Cleanup runs every
            five minutes after file cleanup has processed the events. Zero days
            makes events eligible for the next pass. Saving never deletes
            synchronously; changing back to Unlimited cannot restore deleted
            history.
          </Alert>
        )}
        {errorMessage && (
          <Alert color="red" title="Compacted-event retention update failed">
            {errorMessage}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button loading={saving} disabled={saveDisabled} onClick={onSave}>
            Save compacted-event policy
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
