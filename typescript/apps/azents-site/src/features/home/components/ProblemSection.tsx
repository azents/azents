"use client";

import {
  Box,
  Container,
  Grid,
  Group,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from "@mantine/core";
import {
  IconActivity,
  IconArrowRight,
  IconCloudCog,
  IconHistory,
  IconKey,
  IconRoute,
  IconServerCog,
  IconStack2,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { SectionHeader } from "./SectionHeader";

const benefitKeys = [
  "sessions",
  "scaling",
  "failover",
  "observability",
  "permissions",
  "state",
] as const;

const benefitIcons = {
  failover: IconRoute,
  observability: IconActivity,
  permissions: IconKey,
  scaling: IconCloudCog,
  sessions: IconHistory,
  state: IconStack2,
} as const;

export function ProblemSection(): React.ReactElement {
  const t = useTranslations("problem");

  return (
    <Box
      component="section"
      py={{ base: "5xl", md: "7xl" }}
      style={{ borderBottom: "1px solid rgba(154, 170, 188, 0.12)" }}
    >
      <Container size="xl">
        <Grid gap={{ base: "3xl", md: "4xl" }}>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <SectionHeader
              body={t("body")}
              eyebrow={t("eyebrow")}
              title={t("title")}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Stack gap="sm">
              <Box
                p={{ base: "lg", md: "xl" }}
                style={{
                  background: "rgba(21, 28, 39, 0.68)",
                  border: "1px solid rgba(154, 170, 188, 0.14)",
                  borderRadius: rem(8),
                }}
              >
                <Stack gap="lg">
                  <Group gap="sm">
                    <Text c="dimmed" ff="monospace" size="xs">
                      {t("flow.cloud")}
                    </Text>
                    <IconArrowRight
                      color="var(--mantine-color-dark-2)"
                      size={14}
                    />
                    <Text c="var(--mantine-color-signal-2)" fw={700} size="sm">
                      Azents Runtime
                    </Text>
                    <IconArrowRight
                      color="var(--mantine-color-dark-2)"
                      size={14}
                    />
                    <Text c="dimmed" ff="monospace" size="xs">
                      {t("flow.systems")}
                    </Text>
                  </Group>
                  <Text fw={700} size="xl">
                    {t("panelTitle")}
                  </Text>
                  <Text c="var(--mantine-color-dark-1)" lh={1.6}>
                    {t("panelBody")}
                  </Text>
                </Stack>
              </Box>

              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
                {benefitKeys.map((key) => {
                  const Icon = benefitIcons[key];

                  return (
                    <Box
                      key={key}
                      p="md"
                      style={{
                        background: "rgba(9, 14, 21, 0.74)",
                        border: "1px solid rgba(154, 170, 188, 0.12)",
                        borderRadius: rem(8),
                        minHeight: rem(118),
                      }}
                    >
                      <Stack gap="sm">
                        <ThemeIcon
                          color="signal"
                          radius="md"
                          size="md"
                          variant="light"
                        >
                          <Icon size={16} />
                        </ThemeIcon>
                        <Stack gap={rem(4)}>
                          <Text fw={700} size="sm">
                            {t(`items.${key}.title`)}
                          </Text>
                          <Text c="dimmed" lh={1.5} size="sm">
                            {t(`items.${key}.body`)}
                          </Text>
                        </Stack>
                      </Stack>
                    </Box>
                  );
                })}
              </SimpleGrid>

              <Group gap="xs">
                <ThemeIcon color="signal" radius="md" size="xl" variant="light">
                  <IconServerCog size={28} />
                </ThemeIcon>
                <Text c="dimmed" size="sm">
                  {t("footnote")}
                </Text>
              </Group>
            </Stack>
          </Grid.Col>
        </Grid>
      </Container>
    </Box>
  );
}
