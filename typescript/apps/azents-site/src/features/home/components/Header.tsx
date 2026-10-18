"use client";

import {
  ActionIcon,
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
import { SITE_LINKS } from "@/shared/lib/links";
import { useHeader } from "../containers/useHeader";
import { LocaleSwitcher } from "./LocaleSwitcher";
import type { HeaderViewProps } from "../containers/useHeader";

export function Header(): React.ReactElement {
  return <HeaderView {...useHeader()} />;
}

export function HeaderView({
  onGithub,
  onMobileGithub,
}: HeaderViewProps): React.ReactElement {
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
          <Box lh={0}>
            <AppLogo width={112} />
          </Box>

          <Group gap="xs" wrap="nowrap">
            <LocaleSwitcher />
            <Button
              component="a"
              href={SITE_LINKS.github}
              leftSection={<IconBrandGithub size={18} />}
              onClick={onGithub}
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
                onClick={onMobileGithub}
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
