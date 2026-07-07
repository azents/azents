"use client";

import { Box, Container, rem, VisuallyHidden } from "@mantine/core";
import { useTranslations } from "next-intl";
import Image from "next/image";

export function ProductScreenshotSection(): React.ReactElement {
  const t = useTranslations("productScreenshot");

  return (
    <Box
      component="section"
      aria-label={t("label")}
      py={{ base: "3xl", md: "5xl" }}
      style={{
        background:
          "linear-gradient(180deg, #070a0f 0%, #0a0f18 48%, #070a0f 100%)",
      }}
    >
      <Container size="xl">
        <VisuallyHidden>{t("label")}</VisuallyHidden>

        <Box
          style={{
            background: "#05070b",
            border: "1px solid rgba(148, 163, 184, 0.16)",
            borderRadius: rem(8),
            boxShadow: "0 32px 90px rgba(0, 0, 0, 0.34)",
            overflow: "hidden",
          }}
        >
          <Image
            alt={t("imageAlt")}
            height={1814}
            priority
            sizes="(max-width: 768px) 92vw, 1180px"
            src="/brand/azents/azents-session-screenshot.png"
            style={{
              display: "block",
              height: "auto",
              width: "100%",
            }}
            width={2418}
          />
        </Box>
      </Container>
    </Box>
  );
}
