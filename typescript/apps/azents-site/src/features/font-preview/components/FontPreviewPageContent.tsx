"use client";

import {
  Box,
  Container,
  Grid,
  Group,
  rem,
  Stack,
  Text,
  Title,
} from "@mantine/core";

import type { FontPreviewPageContainerOutput } from "../containers/useFontPreviewPageContainer";
import type { FontPreviewCopy, FontPreviewOption } from "../types";

function FontCard({
  option,
  copy,
}: {
  option: FontPreviewOption;
  copy: FontPreviewCopy;
}): React.ReactElement {
  return (
    <Box
      data-font-preview={option.name}
      p={{ base: "lg", md: "xl" }}
      style={{
        background: "rgba(9, 14, 21, 0.82)",
        border: "1px solid rgba(148, 163, 184, 0.16)",
        borderRadius: rem(8),
        fontFamily: option.stack,
        minHeight: rem(360),
      }}
    >
      <Stack gap="xl">
        <Group justify="space-between">
          <Stack gap={rem(4)}>
            <Text fw={700}>{option.name}</Text>
            <Text c="dimmed" size="sm">
              {option.note}
            </Text>
          </Stack>
          <Text c="dimmed" ff="monospace" size="xs">
            {copy.sampleLabel}
          </Text>
        </Group>

        <Stack gap="lg">
          <Text
            c="var(--mantine-color-signal-2)"
            ff="monospace"
            fw={700}
            size="sm"
            tt="uppercase"
          >
            {copy.eyebrow}
          </Text>
          <Title
            fz={{ base: rem(38), md: rem(52) }}
            lh={1.02}
            order={2}
            style={{ fontFamily: option.stack, letterSpacing: 0 }}
          >
            {copy.headline}
          </Title>
          <Text c="var(--mantine-color-dark-1)" lh={1.55} size="lg">
            {copy.subheadline}
          </Text>
          <Text c="dimmed" lh={1.7}>
            {copy.supporting}
          </Text>
        </Stack>

        <Text c="dimmed" ff="monospace" size="xs">
          {copy.rendered} {option.computedFont}
        </Text>
      </Stack>
    </Box>
  );
}

export function FontPreviewPageContent({
  options,
  copy,
}: FontPreviewPageContainerOutput): React.ReactElement {
  return (
    <Box bg="#070a0f" c="var(--mantine-color-dark-0)" mih="100dvh" py="5xl">
      <Container size="xl">
        <Stack gap="4xl">
          <Stack gap="md">
            <Text
              c="var(--mantine-color-signal-2)"
              ff="monospace"
              fw={700}
              size="sm"
              tt="uppercase"
            >
              {copy.pageEyebrow}
            </Text>
            <Title fz={{ base: rem(42), md: rem(64) }} lh={1} order={1}>
              {copy.pageTitle}
            </Title>
            <Text c="dimmed" maw={rem(760)} size="lg">
              {copy.pageBody}
            </Text>
          </Stack>

          <Grid gap="lg">
            {options.map((option) => (
              <Grid.Col key={option.name} span={{ base: 12, md: 6 }}>
                <FontCard option={option} copy={copy} />
              </Grid.Col>
            ))}
          </Grid>
        </Stack>
      </Container>
    </Box>
  );
}
