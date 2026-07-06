"use client";

import {
  Anchor,
  Box,
  Button,
  Container,
  Grid,
  Group,
  rem,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconBrandGithub, IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { SITE_LINKS } from "@/shared/lib/links";
import { ArchitectureDiagram } from "./ArchitectureDiagram";

export function HeroSection(): React.ReactElement {
  const t = useTranslations("hero");

  return (
    <Box
      component="section"
      id="top"
      pb={{ base: "5xl", md: "7xl" }}
      pt={{ base: "5xl", md: "7xl" }}
      style={{
        borderBottom: "1px solid rgba(154, 170, 188, 0.12)",
      }}
    >
      <Container size="xl">
        <Grid align="center" gap={{ base: "3xl", md: "4xl" }}>
          <Grid.Col span={{ base: 12, md: 7 }}>
            <Stack gap="2xl">
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
                  fz={{ base: rem(42), sm: rem(58), md: rem(68) }}
                  lh={1}
                  order={1}
                  style={{ letterSpacing: 0, maxWidth: rem(820) }}
                >
                  {t("headline")}
                </Title>
                <Text c="var(--mantine-color-dark-1)" lh={1.55} size="xl">
                  {t("subheadline")}
                </Text>
                <Text c="dimmed" lh={1.75} size="lg">
                  {t("supporting")}
                </Text>
              </Stack>
              <Group gap="sm">
                <Button
                  component="a"
                  href={SITE_LINKS.github}
                  leftSection={<IconBrandGithub size={20} />}
                  radius="md"
                  size="lg"
                  target="_blank"
                >
                  {t("cta.github")}
                </Button>
              </Group>
              <Anchor c="dimmed" href={SITE_LINKS.issues} target="_blank">
                <Group gap="xs">
                  <IconMessageCircle size={18} />
                  <Text span>{t("discussion")}</Text>
                </Group>
              </Anchor>
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <ArchitectureDiagram />
          </Grid.Col>
        </Grid>
      </Container>
    </Box>
  );
}
