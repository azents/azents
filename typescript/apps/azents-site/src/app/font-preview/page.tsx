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
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

const fontOptions = [
  {
    name: "Inter Variable",
    stack: "var(--font-azents-sans)",
    noteKey: "current",
  },
  {
    name: "System UI",
    stack:
      "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif",
    noteKey: "native",
  },
  {
    name: "Avenir Next",
    stack:
      "'Avenir Next', Avenir, -apple-system, BlinkMacSystemFont, sans-serif",
    noteKey: "warmer",
  },
  {
    name: "Helvetica Neue",
    stack:
      "'Helvetica Neue', Helvetica, Arial, -apple-system, BlinkMacSystemFont, sans-serif",
    noteKey: "neutral",
  },
  {
    name: "Inter stack",
    stack: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    noteKey: "fallback",
  },
  {
    name: "IBM Plex Sans stack",
    stack:
      "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    noteKey: "fallback",
  },
  {
    name: "Georgia",
    stack: "Georgia, 'Times New Roman', serif",
    noteKey: "editorial",
  },
] as const;

type FontNoteKey = (typeof fontOptions)[number]["noteKey"];

function FontCard({
  name,
  noteKey,
  stack,
}: {
  name: string;
  noteKey: FontNoteKey;
  stack: string;
}): React.ReactElement {
  const t = useTranslations("fontPreview");
  const [computedFont, setComputedFont] = useState<string>(t("checking"));

  useEffect(() => {
    const element = document.querySelector<HTMLElement>(
      `[data-font-preview="${name}"]`,
    );
    if (element) {
      setComputedFont(getComputedStyle(element).fontFamily);
    }
  }, [name]);

  return (
    <Box
      data-font-preview={name}
      p={{ base: "lg", md: "xl" }}
      style={{
        background: "rgba(9, 14, 21, 0.82)",
        border: "1px solid rgba(148, 163, 184, 0.16)",
        borderRadius: rem(8),
        fontFamily: stack,
        minHeight: rem(360),
      }}
    >
      <Stack gap="xl">
        <Group justify="space-between">
          <Stack gap={rem(4)}>
            <Text fw={700}>{name}</Text>
            <Text c="dimmed" size="sm">
              {t(`notes.${noteKey}`)}
            </Text>
          </Stack>
          <Text c="dimmed" ff="monospace" size="xs">
            {t("sampleLabel")}
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
            {t("eyebrow")}
          </Text>
          <Title
            fz={{ base: rem(38), md: rem(52) }}
            lh={1.02}
            order={2}
            style={{ fontFamily: stack, letterSpacing: 0 }}
          >
            {t("headline")}
          </Title>
          <Text c="var(--mantine-color-dark-1)" lh={1.55} size="lg">
            {t("subheadline")}
          </Text>
          <Text c="dimmed" lh={1.7}>
            {t("supporting")}
          </Text>
        </Stack>

        <Text c="dimmed" ff="monospace" size="xs">
          {t("rendered")} {computedFont}
        </Text>
      </Stack>
    </Box>
  );
}

export default function FontPreviewPage(): React.ReactElement {
  const t = useTranslations("fontPreview");

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
              {t("pageEyebrow")}
            </Text>
            <Title fz={{ base: rem(42), md: rem(64) }} lh={1} order={1}>
              {t("pageTitle")}
            </Title>
            <Text c="dimmed" maw={rem(760)} size="lg">
              {t("pageBody")}
            </Text>
          </Stack>

          <Grid gap="lg">
            {fontOptions.map((font) => (
              <Grid.Col key={font.name} span={{ base: 12, md: 6 }}>
                <FontCard {...font} />
              </Grid.Col>
            ))}
          </Grid>
        </Stack>
      </Container>
    </Box>
  );
}
