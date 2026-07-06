"use client";

import { Box, Container, Grid, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { SectionHeader } from "./SectionHeader";

export function BootstrappingSection(): React.ReactElement {
  const t = useTranslations("bootstrapping");
  const rows = [
    t("capabilities.repo"),
    t("capabilities.editing"),
    t("capabilities.shell"),
    t("capabilities.github"),
    t("capabilities.ci"),
    t("capabilities.review"),
  ];

  return (
    <Box component="section" py={{ base: "5xl", md: "7xl" }}>
      <Container size="xl">
        <Grid align="center" gap={{ base: "3xl", md: "4xl" }}>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <SectionHeader
              body={t("body")}
              eyebrow={t("eyebrow")}
              title={t("title")}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Box
              p="xl"
              style={{
                background: "#0c121a",
                border: "1px solid rgba(130, 170, 250, 0.22)",
                borderRadius: rem(8),
              }}
            >
              <Stack gap="md">
                <Text c="dimmed" ff="monospace" size="sm">
                  $ azents run develop-azents
                </Text>
                {rows.map((row) => (
                  <GroupRow key={row} text={row} />
                ))}
              </Stack>
            </Box>
          </Grid.Col>
        </Grid>
      </Container>
    </Box>
  );
}

function GroupRow({ text }: { text: string }): React.ReactElement {
  return (
    <Box
      p="sm"
      style={{
        background: "rgba(7, 10, 15, 0.72)",
        border: "1px solid rgba(154, 170, 188, 0.12)",
        borderRadius: rem(8),
      }}
    >
      <Text c="var(--mantine-color-dark-1)" ff="monospace" size="sm">
        {text}
      </Text>
    </Box>
  );
}
