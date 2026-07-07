"use client";

import {
  ActionIcon,
  Anchor,
  Box,
  Button,
  Container,
  Group,
  rem,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconBrandGithub } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { AppLogo } from "@/shared/components/AppLogo";
import { trackCtaClick, trackSectionNavClick } from "@/shared/lib/analytics";
import { SITE_LINKS } from "@/shared/lib/links";
import { LocaleSwitcher } from "./LocaleSwitcher";

export function Header(): React.ReactElement {
  const t = useTranslations("nav");

  return (
    <Box
      component="header"
      style={{
        backdropFilter: "blur(18px)",
        background: "rgba(7, 10, 15, 0.78)",
        borderBottom: "1px solid rgba(154, 170, 188, 0.14)",
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}
    >
      <Container size="xl">
        <Group h={rem(68)} justify="space-between" wrap="nowrap">
          <Anchor
            href="#top"
            lh={0}
            onClick={() => trackSectionNavClick({ targetSection: "top" })}
          >
            <AppLogo width={112} />
          </Anchor>

          <Group gap="xs" wrap="nowrap">
            <Anchor
              c="dimmed"
              href="#architecture"
              onClick={() =>
                trackSectionNavClick({ targetSection: "architecture" })
              }
              visibleFrom="sm"
            >
              {t("architecture")}
            </Anchor>
            <Anchor
              c="dimmed"
              href="#roadmap"
              onClick={() => trackSectionNavClick({ targetSection: "roadmap" })}
              visibleFrom="sm"
            >
              {t("roadmap")}
            </Anchor>
            <LocaleSwitcher />
            <Button
              component="a"
              href={SITE_LINKS.github}
              leftSection={<IconBrandGithub size={18} />}
              onClick={() =>
                trackCtaClick({
                  ctaId: "header_github",
                  ctaLocation: "header",
                  destinationUrl: SITE_LINKS.github,
                })
              }
              radius="md"
              size="sm"
              target="_blank"
              variant="default"
              visibleFrom="xs"
            >
              <Text span>{t("github")}</Text>
            </Button>
            <Tooltip label={t("github")}>
              <ActionIcon
                component="a"
                href={SITE_LINKS.github}
                onClick={() =>
                  trackCtaClick({
                    ctaId: "header_mobile_github",
                    ctaLocation: "header_mobile",
                    destinationUrl: SITE_LINKS.github,
                  })
                }
                radius="md"
                size="lg"
                target="_blank"
                variant="default"
                hiddenFrom="xs"
              >
                <IconBrandGithub size={20} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </Container>
    </Box>
  );
}
