import {
  ActionIcon,
  Badge,
  Box,
  Code,
  Group,
  Paper,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconChevronDown,
  IconChevronRight,
  IconTool,
} from "@tabler/icons-react";
import type { ProviderToolCall } from "../types";

interface ProviderToolCallCardProps {
  toolCall: ProviderToolCall;
}

function statusColor(status: ProviderToolCall["status"]): string {
  switch (status) {
    case "completed":
      return "green";
    case "failed":
      return "red";
    case "running":
      return "blue";
    case "unknown":
      return "gray";
  }
}

export function ProviderToolCallCard({
  toolCall,
}: ProviderToolCallCardProps): React.ReactElement {
  const [opened, { toggle }] = useDisclosure(false);
  const hasArguments = toolCall.arguments.trim().length > 0;

  return (
    <Paper withBorder radius="md" p="sm" mb="xs" bg="var(--mantine-color-body)">
      <Stack gap="xs">
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon size="sm" variant="light" color="gray">
              <IconTool size={14} />
            </ThemeIcon>
            <Box style={{ minWidth: 0 }}>
              <Text size="sm" fw={600} truncate>
                {toolCall.name}
              </Text>
              <Text size="xs" c="dimmed">
                Provider tool call
              </Text>
            </Box>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Badge
              size="sm"
              color={statusColor(toolCall.status)}
              variant="light"
            >
              {toolCall.status}
            </Badge>
            {hasArguments ? (
              <ActionIcon size="sm" variant="subtle" onClick={toggle}>
                {opened ? (
                  <IconChevronDown size={14} />
                ) : (
                  <IconChevronRight size={14} />
                )}
              </ActionIcon>
            ) : null}
          </Group>
        </Group>
        {hasArguments && opened ? (
          <Code block>{toolCall.arguments}</Code>
        ) : null}
      </Stack>
    </Paper>
  );
}
