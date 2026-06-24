"use client";

/**
 * Hero section component.
 *
 * Top landing page fullscreen hero area.
 * Headline + subheadline + CTA button + ChatPreview.
 */
import { Box, Button, Container, rem, Stack, Text, Title } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChatPreview } from "./ChatPreview";

/** Hero section — main headline, CTA, chat preview */
export function HeroSection(): React.ReactElement {
  const t = useTranslations("hero");

  return (
    <Box
      component="section"
      style={{
        paddingTop: "var(--mantine-spacing-6xl)",
        paddingBottom: rem(80),
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "var(--mantine-color-body) radial-gradient(ellipse at center, rgba(255,255,255,0.06) 0%, transparent 70%)",
      }}
    >
      <Container size="lg">
        <Stack align="center" gap="xl">
          {/* Headline */}
          <Title
            order={1}
            fw={700}
            ta="center"
            style={{
              lineHeight: 1.1,
              fontSize: "clamp(2.5rem, 5vw, 4.5rem)",
            }}
          >
            {t("headline")}
          </Title>

          {/* Subheadline */}
          <Text
            ta="center"
            c="dimmed"
            style={{
              maxWidth: rem(640),
              fontSize: "var(--mantine-font-size-xl)",
              lineHeight: 1.6,
              whiteSpace: "pre-line",
            }}
          >
            {t("subheadline")}
          </Text>

          {/* CTA button */}
          <Button
            component={Link}
            href="/login?next=/workspaces"
            size="lg"
            radius="xl"
          >
            {t("cta")}
          </Button>

          {/* Chat preview */}
          <Box mt={rem(60)} w="100%">
            <ChatPreview />
          </Box>
        </Stack>
      </Container>
    </Box>
  );
}
