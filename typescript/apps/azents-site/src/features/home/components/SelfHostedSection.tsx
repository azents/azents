"use client";

import { Badge, Box, Container, Group, rem, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { SectionHeader } from "./SectionHeader";

export function SelfHostedSection(): React.ReactElement {
  const t = useTranslations("selfHosted");
  const keywords = [
    t("keywords.data"),
    t("keywords.security"),
    t("keywords.internal"),
    t("keywords.regulatory"),
    t("keywords.privateCloud"),
  ];

  return (
    <Box component="section" py={{ base: "5xl", md: "7xl" }}>
      <Container size="xl">
        <Stack gap="4xl">
          <SectionHeader
            body={t("body")}
            eyebrow={t("eyebrow")}
            title={t("title")}
          />
          <Box
            p={{ base: "lg", md: "xl" }}
            style={{
              background: "#0c121a",
              border: "1px solid rgba(154, 170, 188, 0.14)",
              borderRadius: rem(8),
            }}
          >
            <Stack gap="lg">
              <Text c="var(--mantine-color-dark-1)" lh={1.7} size="xl">
                {t("thesis")}
              </Text>
              <Group gap="sm">
                {keywords.map((keyword) => (
                  <Badge
                    key={keyword}
                    color="graphite"
                    ff="monospace"
                    radius="sm"
                    size="lg"
                    variant="outline"
                  >
                    {keyword}
                  </Badge>
                ))}
              </Group>
            </Stack>
          </Box>
        </Stack>
      </Container>
    </Box>
  );
}
