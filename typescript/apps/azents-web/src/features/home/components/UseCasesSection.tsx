"use client";

/** Use Cases section — introduces real use cases with Before/After comparison */
import { Box, Container, em, rem, Text, Title } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useTranslations } from "next-intl";

/** Use case keys in useCases namespace */
type UseCaseKey = "design" | "marketing" | "operations" | "engineering";

/** Individual use case card definition */
interface UseCaseCard {
  key: UseCaseKey;
  agentColor: string;
}

/** Use case list — includes unique color for each agent */
const USE_CASE_CARDS: UseCaseCard[] = [
  { key: "design", agentColor: "var(--mantine-color-blue-6)" },
  { key: "marketing", agentColor: "var(--mantine-color-violet-6)" },
  { key: "operations", agentColor: "var(--mantine-color-teal-6)" },
  { key: "engineering", agentColor: "var(--mantine-color-orange-6)" },
];

export function UseCasesSection(): React.ReactElement {
  const t = useTranslations("useCases");
  const tc = useTranslations("common");
  const isDesktop = useMediaQuery(`(min-width: ${em(768)})`);

  return (
    <Box
      component="section"
      style={{
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
              color: "var(--mantine-color-blue-6)",
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
              marginBottom: "var(--mantine-spacing-md)",
            }}
          >
            {t("headline")}
          </Title>
          <Text
            c="dimmed"
            style={{
              maxWidth: rem(560),
              fontSize: "var(--mantine-font-size-lg)",
              lineHeight: 1.6,
            }}
          >
            {t("subheadline")}
          </Text>
        </Box>

        {/* Use case card grid */}
        <Box
          style={{
            display: "grid",
            gridTemplateColumns: isDesktop ? "repeat(2, 1fr)" : "1fr",
            gap: "var(--mantine-spacing-lg)",
          }}
        >
          {USE_CASE_CARDS.map((card) => (
            <Box
              key={card.key}
              style={{
                backgroundColor: "var(--mantine-color-dark-8)",
                border: `${rem(1)} solid var(--mantine-color-default-border)`,
                borderRadius: "var(--mantine-radius-lg)",
                padding: rem(36),
              }}
            >
              {/* Card title */}
              <Text
                fw={600}
                style={{
                  fontSize: rem(22),
                }}
              >
                {t(`${card.key}.title`)}
              </Text>

              {/* Agent name — monospace emphasis */}
              <Text
                style={{
                  fontFamily: "var(--font-geist-mono), monospace",
                  color: card.agentColor,
                  fontSize: rem(15),
                  marginTop: "var(--mantine-spacing-2xs)",
                }}
              >
                {t(`${card.key}.agent`)}
              </Text>

              {/* Tagline */}
              <Text
                fw={500}
                style={{
                  marginTop: "var(--mantine-spacing-md)",
                  fontSize: "var(--mantine-font-size-md)",
                }}
              >
                {t(`${card.key}.tagline`)}
              </Text>

              {/* Description */}
              <Text
                c="dimmed"
                style={{
                  marginTop: "var(--mantine-spacing-sm)",
                  fontSize: rem(15),
                  lineHeight: 1.7,
                }}
              >
                {t(`${card.key}.description`)}
              </Text>

              {/* Before / After comparison */}
              <Box
                style={{
                  marginTop: rem(28),
                  padding: "var(--mantine-spacing-lg)",
                  backgroundColor:
                    "color-mix(in srgb, var(--mantine-color-white) 2%, transparent)",
                  borderRadius: rem(12),
                  border: `${rem(1)} solid var(--mantine-color-default-border)`,
                }}
              >
                {/* Before */}
                <Box>
                  <Text
                    fw={600}
                    c="dimmed"
                    style={{
                      textTransform: "uppercase",
                      letterSpacing: rem(1),
                      fontSize: "var(--mantine-font-size-xs)",
                    }}
                  >
                    {tc("before")}
                  </Text>
                  <Text
                    c="dimmed"
                    style={{
                      marginTop: "var(--mantine-spacing-2xs)",
                      fontSize: rem(15),
                      lineHeight: 1.5,
                    }}
                  >
                    {t(`${card.key}.before`)}
                  </Text>
                </Box>

                {/* Divider */}
                <Box
                  style={{
                    height: rem(1),
                    backgroundColor: "var(--mantine-color-default-border)",
                    marginTop: "var(--mantine-spacing-md)",
                    marginBottom: "var(--mantine-spacing-md)",
                  }}
                />

                {/* After */}
                <Box>
                  <Text
                    fw={600}
                    style={{
                      textTransform: "uppercase",
                      letterSpacing: rem(1),
                      fontSize: "var(--mantine-font-size-xs)",
                    }}
                  >
                    {tc("after")}
                  </Text>
                  <Text
                    style={{
                      marginTop: "var(--mantine-spacing-2xs)",
                      fontSize: rem(15),
                      lineHeight: 1.5,
                    }}
                  >
                    {t(`${card.key}.after`)}
                  </Text>
                </Box>
              </Box>

              {/* Time saved badge */}
              <Box
                style={{
                  display: "inline-block",
                  marginTop: "var(--mantine-spacing-lg)",
                  padding: `${rem(6)} ${rem(16)}`,
                  borderRadius: rem(20),
                  backgroundColor:
                    "color-mix(in srgb, var(--mantine-color-teal-6) 10%, transparent)",
                  border: `${rem(1)} solid color-mix(in srgb, var(--mantine-color-teal-6) 20%, transparent)`,
                }}
              >
                <Text
                  fw={500}
                  style={{
                    color: "var(--mantine-color-teal-6)",
                    fontSize: "var(--mantine-font-size-sm)",
                  }}
                >
                  {tc("timeSaved")}: {t(`${card.key}.timeSaved`)}
                </Text>
              </Box>
            </Box>
          ))}
        </Box>
      </Container>
    </Box>
  );
}
