"use client";

import {
  Badge,
  Box,
  Container,
  Grid,
  Group,
  rem,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { SectionHeader } from "./SectionHeader";

export function RoadmapSection(): React.ReactElement {
  const t = useTranslations("roadmap");
  const audience = [
    t("audience.platform"),
    t("audience.devops"),
    t("audience.builders"),
    t("audience.selfHosted"),
    t("audience.sensitive"),
  ];
  const roadmap = [
    t("items.deployment"),
    t("items.reliability"),
    t("items.providers"),
    t("items.harness"),
    t("items.observability"),
    t("items.localLlm"),
    t("items.workflows"),
  ];

  return (
    <Box
      component="section"
      id="roadmap"
      py={{ base: "5xl", md: "7xl" }}
      style={{ background: "#0a0f18" }}
    >
      <Container size="xl">
        <Grid gap={{ base: "3xl", md: "4xl" }}>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <Stack gap="xl">
              <SectionHeader
                body={t("body")}
                eyebrow={t("eyebrow")}
                title={t("title")}
              />
              <Group gap="sm">
                {audience.map((item) => (
                  <Badge
                    key={item}
                    color="signal"
                    radius="sm"
                    size="lg"
                    variant="light"
                  >
                    {item}
                  </Badge>
                ))}
              </Group>
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Box
              p="xl"
              style={{
                background: "rgba(21, 28, 39, 0.7)",
                border: "1px solid rgba(154, 170, 188, 0.14)",
                borderRadius: rem(8),
              }}
            >
              <Stack gap="md">
                <Text fw={700} size="xl">
                  {t("currentFocus")}
                </Text>
                {roadmap.map((item) => (
                  <Box
                    key={item}
                    p="sm"
                    style={{
                      borderBottom: "1px solid rgba(154, 170, 188, 0.1)",
                    }}
                  >
                    <Text c="dimmed">{item}</Text>
                  </Box>
                ))}
              </Stack>
            </Box>
          </Grid.Col>
        </Grid>
      </Container>
    </Box>
  );
}
