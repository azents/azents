"use client";

import { Anchor, Box, Container, Group, rem, Text } from "@mantine/core";
import { IconBrandGithub, IconMessageCircle } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { SITE_LINKS } from "@/shared/lib/links";

export function PageFooter(): React.ReactElement {
  const t = useTranslations("footer");

  return (
    <Box
      component="footer"
      py="xl"
      style={{
        borderTop: "1px solid rgba(154, 170, 188, 0.12)",
      }}
    >
      <Container size="xl">
        <Group justify="space-between">
          <Text c="dimmed" size="sm">
            {t("tagline")}
          </Text>
          <Group gap="lg">
            <Anchor c="dimmed" href={SITE_LINKS.github} target="_blank">
              <Group gap={rem(6)}>
                <IconBrandGithub size={16} />
                <Text span size="sm">
                  {t("github")}
                </Text>
              </Group>
            </Anchor>
            <Anchor c="dimmed" href={SITE_LINKS.issues} target="_blank">
              <Group gap={rem(6)}>
                <IconMessageCircle size={16} />
                <Text span size="sm">
                  {t("discussion")}
                </Text>
              </Group>
            </Anchor>
          </Group>
        </Group>
      </Container>
    </Box>
  );
}
