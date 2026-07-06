"use client";

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
import { IconBrandGithub } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { SITE_LINKS } from "@/shared/lib/links";

export function CtaSection(): React.ReactElement {
  const t = useTranslations("finalCta");

  return (
    <Box component="section" py={{ base: "5xl", md: "7xl" }}>
      <Container size="lg">
        <Box
          p={{ base: "xl", md: "3xl" }}
          style={{
            background:
              "linear-gradient(180deg, rgba(21, 28, 39, 0.92), rgba(12, 18, 26, 0.92))",
            border: "1px solid rgba(130, 170, 250, 0.24)",
            borderRadius: rem(8),
          }}
        >
          <Stack align="center" gap="xl" ta="center">
            <Title fz={{ base: rem(36), md: rem(54) }} lh={1.05} order={2}>
              {t("title")}
            </Title>
            <Text c="dimmed" lh={1.7} maw={rem(720)} size="lg">
              {t("body")}
            </Text>
            <Group justify="center">
              <Button
                component="a"
                href={SITE_LINKS.github}
                leftSection={<IconBrandGithub size={20} />}
                radius="md"
                size="lg"
                target="_blank"
              >
                {t("github")}
              </Button>
            </Group>
          </Stack>
        </Box>
      </Container>
    </Box>
  );
}
