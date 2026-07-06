"use client";

import { Box, rem, Stack, Text, Title } from "@mantine/core";

export function SectionHeader({
  eyebrow,
  title,
  body,
}: {
  body: string;
  eyebrow: string;
  title: string;
}): React.ReactElement {
  return (
    <Stack gap="sm" maw={rem(760)}>
      <Text c="var(--mantine-color-signal-2)" ff="monospace" fw={700} size="sm">
        {eyebrow}
      </Text>
      <Title fz={{ base: rem(34), md: rem(48) }} lh={1.05} order={2}>
        {title}
      </Title>
      <Box maw={rem(680)}>
        <Text c="dimmed" lh={1.7} size="lg">
          {body}
        </Text>
      </Box>
    </Stack>
  );
}
