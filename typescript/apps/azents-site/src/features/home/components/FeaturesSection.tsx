"use client";

import { Box, Container, Grid, Group, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { SectionHeader } from "./SectionHeader";

type FeatureKey =
  | "harness"
  | "history"
  | "permissions"
  | "providers"
  | "separation"
  | "sessions"
  | "tools";

function FeatureRow({
  body,
  index,
  title,
}: {
  body: string;
  index: number;
  title: string;
}): React.ReactElement {
  return (
    <Box
      py="md"
      style={{
        borderTop: "1px solid rgba(148, 163, 184, 0.14)",
      }}
    >
      <Grid align="baseline" gap="lg">
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Group gap="md" wrap="nowrap">
            <Text c="dimmed" ff="monospace" size="xs">
              {String(index + 1).padStart(2, "0")}
            </Text>
            <Text fw={700}>{title}</Text>
          </Group>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Text c="dimmed" lh={1.65}>
            {body}
          </Text>
        </Grid.Col>
      </Grid>
    </Box>
  );
}

export function FeaturesSection(): React.ReactElement {
  const t = useTranslations("features");
  const featureKeys: FeatureKey[] = [
    "sessions",
    "history",
    "separation",
    "permissions",
    "providers",
    "harness",
    "tools",
  ];

  return (
    <Box
      component="section"
      py={{ base: "5xl", md: "7xl" }}
      style={{ background: "#070a0f" }}
    >
      <Container size="xl">
        <Stack gap="5xl">
          <Grid>
            <Grid.Col span={{ base: 12, md: 7 }}>
              <SectionHeader
                body={t("body")}
                eyebrow={t("eyebrow")}
                title={t("title")}
              />
            </Grid.Col>
          </Grid>
          <Box
            p={{ base: "lg", md: "xl" }}
            style={{
              background: "rgba(9, 14, 21, 0.82)",
              border: "1px solid rgba(148, 163, 184, 0.16)",
              borderRadius: rem(6),
            }}
          >
            {featureKeys.map((featureKey, index) => (
              <FeatureRow
                key={featureKey}
                body={t(`items.${featureKey}.body`)}
                index={index}
                title={t(`items.${featureKey}.title`)}
              />
            ))}
          </Box>
        </Stack>
      </Container>
    </Box>
  );
}
