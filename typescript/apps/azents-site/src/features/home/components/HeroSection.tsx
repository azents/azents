"use client";

import {
  Anchor,
  Box,
  Button,
  Container,
  Group,
  rem,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconBrandGithub, IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { trackCtaClick, trackDiscussionClick } from "@/shared/lib/analytics";
import { SITE_LINKS } from "@/shared/lib/links";

export function HeroSection(): React.ReactElement {
  const t = useTranslations("hero");

  return (
    <Box
      component="section"
      id="top"
      pb={{ base: rem(96), md: rem(136) }}
      pt={{ base: rem(104), md: rem(152) }}
      style={{
        backgroundImage:
          "linear-gradient(180deg, rgba(7, 10, 15, 0) 62%, #070a0f 100%), linear-gradient(90deg, rgba(7, 10, 15, 0.98) 0%, rgba(7, 10, 15, 0.92) 36%, rgba(7, 10, 15, 0.66) 62%, rgba(7, 10, 15, 0.34) 100%), linear-gradient(180deg, rgba(7, 10, 15, 0.22) 0%, rgba(7, 10, 15, 0.48) 100%), url('/brand/azents/azents-hero-background.png')",
        backgroundPosition: "center right",
        backgroundRepeat: "no-repeat",
        backgroundSize: "cover",
        minHeight: "min(860px, calc(100vh - 64px))",
      }}
    >
      <Container size="xl">
        <Stack gap="2xl" maw={rem(760)}>
          <Text
            c="var(--mantine-color-signal-2)"
            ff="monospace"
            fw={700}
            size="sm"
            tt="uppercase"
          >
            {t("eyebrow")}
          </Text>
          <Stack gap="xl">
            <Title
              fz={{ base: rem(42), sm: rem(58), md: rem(72) }}
              lh={1}
              order={1}
              style={{ letterSpacing: 0, maxWidth: rem(820) }}
            >
              {t("headline")}
            </Title>
            <Text
              c="var(--mantine-color-dark-1)"
              lh={1.55}
              maw={rem(660)}
              size="xl"
            >
              {t("subheadline")}
            </Text>
            <Text c="dimmed" lh={1.75} maw={rem(640)} size="lg">
              {t("supporting")}
            </Text>
          </Stack>
          <Group gap="sm">
            <Button
              component="a"
              href={SITE_LINKS.github}
              leftSection={<IconBrandGithub size={20} />}
              onClick={() =>
                trackCtaClick({
                  ctaId: "hero_github",
                  ctaLocation: "hero",
                  destinationUrl: SITE_LINKS.github,
                })
              }
              radius="md"
              size="lg"
              target="_blank"
            >
              {t("cta.github")}
            </Button>
          </Group>
          <Anchor
            c="dimmed"
            href={SITE_LINKS.issues}
            onClick={() => trackDiscussionClick("hero")}
            target="_blank"
          >
            <Group gap="xs">
              <IconMessageCircle size={18} />
              <Text span>{t("discussion")}</Text>
            </Group>
          </Anchor>
        </Stack>
      </Container>
    </Box>
  );
}
