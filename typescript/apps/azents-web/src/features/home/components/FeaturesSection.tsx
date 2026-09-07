"use client";

/** Features section — introduces main features with Bento Grid layout */
import { Box, Container, rem, Text, Title } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import {
  IconBolt,
  IconNetwork,
  IconPuzzle,
  IconRocket,
  IconShield,
  IconUsers,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";

/** Feature card keys in features namespace */
type FeatureKey =
  | "teamAgents"
  | "uiBuilder"
  | "batteryIncluded"
  | "security"
  | "automation"
  | "multiAgent";

/** Individual feature card definition */
interface FeatureCard {
  key: FeatureKey;
  icon: React.ComponentType<{ size?: number; color?: string }>;
  accentColor: string;
  /** Grid column span on desktop */
  colSpan: number;
}

/** Feature card list — layout emphasizing direct agent creation most */
const FEATURE_CARDS: FeatureCard[] = [
  { key: "uiBuilder", icon: IconPuzzle, accentColor: "#8b5cf6", colSpan: 2 },
  { key: "teamAgents", icon: IconUsers, accentColor: "#0070f3", colSpan: 1 },
  {
    key: "batteryIncluded",
    icon: IconBolt,
    accentColor: "#10b981",
    colSpan: 1,
  },
  { key: "automation", icon: IconRocket, accentColor: "#06b6d4", colSpan: 2 },
  { key: "security", icon: IconShield, accentColor: "#f97316", colSpan: 2 },
  { key: "multiAgent", icon: IconNetwork, accentColor: "#ec4899", colSpan: 1 },
];

export function FeaturesSection(): React.ReactElement {
  const t = useTranslations("features");
  const isDesktop = useMediaQuery("(min-width: 768px)");

  return (
    <Box
      component="section"
      style={{
        background:
          "linear-gradient(to bottom, var(--mantine-color-dark-8), var(--mantine-color-default))",
        paddingTop: "var(--mantine-spacing-5xl)",
        paddingBottom: "var(--mantine-spacing-5xl)",
      }}
    >
      <Container size="lg">
        {/* Section header */}
        <Box style={{ marginBottom: "var(--mantine-spacing-3xl)" }}>
          <Text
            style={{
              fontFamily: "var(--font-geist-mono), monospace",
              fontSize: "var(--mantine-font-size-sm)",
              color: "#0070f3",
              textTransform: "uppercase",
              letterSpacing: rem(2),
              marginBottom: "var(--mantine-spacing-md)",
            }}
          >
            {t("sectionTag")}
          </Text>
          <Title
            order={2}
            style={{
              fontSize: "clamp(1.75rem, 4vw, 2.625rem)",
              fontWeight: 700,
            }}
          >
            {t("headline")}
          </Title>
        </Box>

        {/* Bento Grid */}
        <Box
          style={{
            display: "grid",
            gridTemplateColumns: isDesktop ? "repeat(3, 1fr)" : "1fr",
            gap: "var(--mantine-spacing-lg)",
          }}
        >
          {FEATURE_CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <Box
                key={card.key}
                style={{
                  ...(isDesktop && { gridColumn: `span ${card.colSpan}` }),
                  backgroundColor: "var(--mantine-color-dark-8)",
                  border: "1px solid var(--mantine-color-default-border)",
                  borderRadius: "var(--mantine-radius-lg)",
                  padding: rem(36),
                  position: "relative",
                  overflow: "hidden",
                }}
              >
                {/* Top radial gradient overlay */}
                <Box
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    height: rem(200),
                    background: `radial-gradient(ellipse at top, rgba(${hexToRgb(card.accentColor)}, 0.15), transparent 70%)`,
                    pointerEvents: "none",
                  }}
                />

                {/* Card content */}
                <Box style={{ position: "relative", zIndex: 1 }}>
                  <Icon size={40} color={card.accentColor} />
                  <Text
                    fw={600}
                    style={{
                      marginTop: "var(--mantine-spacing-lg)",
                      fontSize: rem(22),
                    }}
                  >
                    {t(`${card.key}.title`)}
                  </Text>
                  <Text
                    c="dimmed"
                    style={{
                      marginTop: "var(--mantine-spacing-xs)",
                      fontSize: "var(--mantine-font-size-md)",
                      lineHeight: 1.7,
                    }}
                  >
                    {t(`${card.key}.description`)}
                  </Text>
                </Box>
              </Box>
            );
          })}
        </Box>
      </Container>
    </Box>
  );
}

/** Utility converting hex color to RGB string */
function hexToRgb(hex: string): string {
  const result = /^#([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result || result.length < 4) {
    return "0, 0, 0";
  }
  const r = result[1] ?? "00";
  const g = result[2] ?? "00";
  const b = result[3] ?? "00";
  return `${parseInt(r, 16)}, ${parseInt(g, 16)}, ${parseInt(b, 16)}`;
}
