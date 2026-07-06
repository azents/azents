"use client";

import {
  Box,
  Container,
  Grid,
  rem,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { ArchitectureDiagram } from "./ArchitectureDiagram";
import { SectionHeader } from "./SectionHeader";

function Term({
  body,
  title,
}: {
  body: string;
  title: string;
}): React.ReactElement {
  return (
    <Box
      p="lg"
      style={{
        background: "rgba(21, 28, 39, 0.66)",
        border: "1px solid rgba(154, 170, 188, 0.14)",
        borderRadius: rem(8),
      }}
    >
      <Stack gap="xs">
        <Text c="var(--mantine-color-signal-2)" ff="monospace" fw={700}>
          {title}
        </Text>
        <Text c="dimmed" lh={1.6} size="sm">
          {body}
        </Text>
      </Stack>
    </Box>
  );
}

export function ArchitectureSection(): React.ReactElement {
  const t = useTranslations("architecture");
  const terms = [
    { title: t("terms.engine.title"), body: t("terms.engine.body") },
    { title: t("terms.runtime.title"), body: t("terms.runtime.body") },
    { title: t("terms.session.title"), body: t("terms.session.body") },
    { title: t("terms.toolkit.title"), body: t("terms.toolkit.body") },
  ];

  return (
    <Box
      component="section"
      id="architecture"
      py={{ base: "5xl", md: "7xl" }}
      style={{ background: "#0a0f18" }}
    >
      <Container size="xl">
        <Stack gap="5xl">
          <Grid gap={{ base: "3xl", md: "4xl" }}>
            <Grid.Col span={{ base: 12, lg: 5 }}>
              <SectionHeader
                body={t("body")}
                eyebrow={t("eyebrow")}
                title={t("title")}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <ArchitectureDiagram />
            </Grid.Col>
          </Grid>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
            {terms.map((term) => (
              <Term key={term.title} body={term.body} title={term.title} />
            ))}
          </SimpleGrid>
        </Stack>
      </Container>
    </Box>
  );
}
