"use client";

/** CTA section — signup encouragement area */
import {
  Box,
  Button,
  Container,
  Group,
  rem,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";

export function CtaSection(): React.ReactElement {
  const t = useTranslations("cta");

  return (
    <Box
      component="section"
      style={{
        background:
          "linear-gradient(to bottom, var(--mantine-color-dark-8), var(--mantine-color-default))",
        position: "relative",
        overflow: "hidden",
        paddingTop: "var(--mantine-spacing-6xl)",
        paddingBottom: "var(--mantine-spacing-6xl)",
      }}
    >
      {/* Top center radial glow */}
      <Box
        style={{
          position: "absolute",
          top: 0,
          left: "50%",
          transform: "translateX(-50%)",
          width: rem(600),
          height: rem(300),
          background:
            "radial-gradient(ellipse at center top, rgba(255,255,255,0.04), transparent 70%)",
          pointerEvents: "none",
        }}
      />

      <Container size="sm" style={{ position: "relative", zIndex: 1 }}>
        <Stack align="center" gap="lg">
          <Title
            order={2}
            style={{
              fontSize: rem(40),
              fontWeight: 700,
              textAlign: "center",
            }}
          >
            {t("headline")}
          </Title>

          <Text
            c="dimmed"
            style={{
              textAlign: "center",
              maxWidth: rem(480),
              fontSize: "var(--mantine-font-size-xl)",
              lineHeight: 1.6,
            }}
          >
            {t("subheadline")}
          </Text>

          <Group gap="md" mt="md">
            <Button component={Link} href="/login?next=/workspaces" size="lg">
              {t("primary")}
            </Button>

            <Button
              size="lg"
              variant="outline"
              style={{
                borderColor: "var(--mantine-color-default-border)",
              }}
            >
              {t("secondary")}
            </Button>
          </Group>
        </Stack>
      </Container>
    </Box>
  );
}
