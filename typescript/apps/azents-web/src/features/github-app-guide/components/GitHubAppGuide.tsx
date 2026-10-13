"use client";

import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Code,
  Container,
  Divider,
  Group,
  List,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconBrandGithub,
  IconExternalLink,
  IconLock,
  IconShieldCheck,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import classes from "./GitHubAppGuide.module.css";
import type { ReactElement, ReactNode } from "react";

const GUIDE_STEPS = [
  "register",
  "settings",
  "permissions",
  "values",
  "install",
  "finish",
] as const;
type GuideStep = (typeof GUIDE_STEPS)[number];

const CORE_PERMISSIONS = ["repos", "issues", "pull_requests", "users"] as const;
const EXTRA_PERMISSIONS = [
  "actions",
  "discussions",
  "code_security",
  "orgs",
  "projects",
  "notifications",
] as const;
type PermissionGroup =
  (typeof CORE_PERMISSIONS)[number] | (typeof EXTRA_PERMISSIONS)[number];

const GUIDE_SOURCES = [
  {
    key: "register",
    href: "https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app",
  },
  {
    key: "permissions",
    href: "https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app",
  },
  {
    key: "privateKeys",
    href: "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps",
  },
  {
    key: "tokens",
    href: "https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens#configuring-your-app-to-use-user-access-tokens-that-expire",
  },
  {
    key: "install",
    href: "https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app",
  },
  {
    key: "api",
    href: "https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps",
  },
  {
    key: "notifications",
    href: "https://docs.github.com/en/rest/activity/notifications#list-notifications-for-the-authenticated-user",
  },
] as const;

function GuideSection({
  step,
  number,
  children,
}: {
  step: GuideStep;
  number: number;
  children: ReactNode;
}): ReactElement {
  const t = useTranslations("githubAppGuide");
  return (
    <Box
      component="section"
      id={step}
      aria-labelledby={`guide-${step}`}
      className={classes.section}
    >
      <Stack gap="md">
        <Title order={2} size="h3" id={`guide-${step}`}>
          {number}. {t(`steps.${step}.title`)}
        </Title>
        <Stack gap="md" className={classes.sectionBody}>
          {children}
        </Stack>
      </Stack>
    </Box>
  );
}

function PermissionRow({ group }: { group: PermissionGroup }): ReactElement {
  const t = useTranslations("githubAppGuide");
  return (
    <Stack component="section" gap="xs" py="md" className={classes.permission}>
      <Group gap="xs">
        <Text component="h3" size="sm" fw={600} m={0}>
          {t(`permissions.${group}.title`)}
        </Text>
        <Code>{group}</Code>
      </Group>
      <SimpleGrid
        cols={{ base: 1, sm: 2 }}
        spacing="lg"
        verticalSpacing="sm"
        className={classes.permissionColumns}
      >
        <Stack gap="xs">
          <Text size="xs" c="dimmed" fw={600}>
            {t("steps.permissions.read")}
          </Text>
          <Text size="sm">{t(`permissions.${group}.read`)}</Text>
        </Stack>
        <Stack gap="xs">
          <Text size="xs" c="dimmed" fw={600}>
            {t("steps.permissions.write")}
          </Text>
          <Text size="sm">{t(`permissions.${group}.write`)}</Text>
        </Stack>
      </SimpleGrid>
    </Stack>
  );
}

export function GitHubAppGuide(): ReactElement {
  const t = useTranslations("githubAppGuide");
  return (
    <Container
      component="main"
      size="md"
      py="xl"
      px={{ base: "md", sm: "xl" }}
      className={classes.guide}
    >
      <Stack gap="xl">
        <Stack gap="sm" align="flex-start">
          <ThemeIcon
            size={rem(40)}
            variant="light"
            radius="md"
            className={classes.headerIcon}
            aria-hidden
          >
            <IconBrandGithub size={rem(24)} />
          </ThemeIcon>
          <Title order={1} size="h2">
            {t("title")}
          </Title>
          <Text c="dimmed">{t("intro")}</Text>
        </Stack>
        <Box component="nav" aria-label={t("contents")}>
          <Group gap="xs">
            {GUIDE_STEPS.map((step, index) => (
              <Anchor key={step} href={`#${step}`} size="sm">
                {index + 1}. {t(`steps.${step}.title`)}
              </Anchor>
            ))}
          </Group>
        </Box>
        <Alert color="yellow" variant="light">
          <Stack gap="xs">
            <IconLock size={rem(20)} aria-hidden />
            <Text size="sm">{t("safety")}</Text>
          </Stack>
        </Alert>
        <Divider />
        <GuideSection step="register" number={1}>
          <List spacing="sm">
            <List.Item>{t("steps.register.personal")}</List.Item>
            <List.Item>{t("steps.register.organization")}</List.Item>
          </List>
          <Button
            component="a"
            href="https://github.com/settings/apps/new"
            target="_blank"
            rel="noopener noreferrer"
            title={t("opensNewTab")}
            variant="light"
            leftSection={<IconBrandGithub size={rem(18)} />}
            rightSection={<IconExternalLink size={rem(16)} />}
            h="auto"
            py="sm"
            w="fit-content"
            styles={{ label: { whiteSpace: "normal", textAlign: "left" } }}
          >
            {t("steps.register.open")}
          </Button>
        </GuideSection>
        <Divider />
        <GuideSection step="settings" number={2}>
          <List type="ordered" spacing="sm">
            <List.Item>{t("steps.settings.name")}</List.Item>
            <List.Item>{t("steps.settings.callback")}</List.Item>
            <List.Item>{t("steps.settings.tokenExpiry")}</List.Item>
            <List.Item>{t("steps.settings.authorization")}</List.Item>
            <List.Item>{t("steps.settings.webhook")}</List.Item>
            <List.Item>{t("steps.settings.visibility")}</List.Item>
          </List>
        </GuideSection>
        <Divider />
        <GuideSection step="permissions" number={3}>
          <Text>{t("steps.permissions.intro")}</Text>
          <Alert variant="light">
            <Stack gap="xs">
              <IconShieldCheck size={rem(20)} aria-hidden />
              <Text size="sm">{t("steps.permissions.metadata")}</Text>
            </Stack>
          </Alert>
          <Box>
            <Text size="sm" fw={600}>
              {t("steps.permissions.feature")}
            </Text>
            {CORE_PERMISSIONS.map((group) => (
              <PermissionRow group={group} key={group} />
            ))}
          </Box>
          <Accordion variant="contained">
            <Accordion.Item value="additional-permissions">
              <Accordion.Control>
                {t("steps.permissions.more")}
              </Accordion.Control>
              <Accordion.Panel>
                {EXTRA_PERMISSIONS.map((group) => (
                  <PermissionRow group={group} key={group} />
                ))}
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
          <Text size="sm" c="dimmed">
            {t("steps.permissions.specific")}
          </Text>
          <Text fw={600}>{t("steps.permissions.save")}</Text>
        </GuideSection>
        <Divider />
        <GuideSection step="values" number={4}>
          <Text>{t("steps.values.intro")}</Text>
          <List type="ordered" spacing="md">
            <List.Item>{t("steps.values.appId")}</List.Item>
            <List.Item>{t("steps.values.clientId")}</List.Item>
            <List.Item>{t("steps.values.clientSecret")}</List.Item>
            <List.Item>{t("steps.values.privateKey")}</List.Item>
          </List>
          <Alert color="yellow">
            <Stack gap="xs">
              <IconLock size={rem(20)} aria-hidden />
              <Text size="sm">{t("steps.values.warning")}</Text>
            </Stack>
          </Alert>
        </GuideSection>
        <Divider />
        <GuideSection step="install" number={5}>
          <List type="ordered" spacing="sm">
            <List.Item>{t("steps.install.path")}</List.Item>
            <List.Item>{t("steps.install.account")}</List.Item>
            <List.Item>{t("steps.install.id")}</List.Item>
          </List>
          <Alert color="yellow">{t("steps.install.pending")}</Alert>
        </GuideSection>
        <Divider />
        <GuideSection step="finish" number={6}>
          <List type="ordered" spacing="sm">
            <List.Item>{t("steps.finish.values")}</List.Item>
            <List.Item>{t("steps.finish.verify")}</List.Item>
            <List.Item>{t("steps.finish.save")}</List.Item>
          </List>
          <Alert>
            <Stack gap="xs">
              <IconShieldCheck size={rem(20)} aria-hidden />
              <Text size="sm">{t("steps.finish.sharing")}</Text>
            </Stack>
          </Alert>
        </GuideSection>
        <Divider />
        <Box component="section" aria-labelledby="guide-troubleshooting">
          <Stack gap="md">
            <Title order={2} size="h3" id="guide-troubleshooting">
              {t("troubleshooting.title")}
            </Title>
            <List spacing="sm">
              <List.Item>{t("troubleshooting.callback")}</List.Item>
              <List.Item>{t("troubleshooting.credentials")}</List.Item>
              <List.Item>{t("troubleshooting.access")}</List.Item>
            </List>
          </Stack>
        </Box>
        <Box component="section" aria-labelledby="guide-sources">
          <Stack gap="sm">
            <Group gap="sm">
              <Title order={2} size="h3" id="guide-sources">
                {t("sources.title")}
              </Title>
              <Badge variant="light">GitHub Docs</Badge>
            </Group>
            <Text size="sm" c="dimmed">
              {t("sources.intro")}
            </Text>
            {GUIDE_SOURCES.map(({ key, href }) => (
              <Anchor
                href={href}
                key={key}
                target="_blank"
                rel="noopener noreferrer"
                title={t("opensNewTab")}
                size="sm"
                className={classes.sourcesLink}
              >
                {t(`sources.${key}`)}
                <IconExternalLink size={rem(14)} aria-hidden />
              </Anchor>
            ))}
          </Stack>
        </Box>
      </Stack>
    </Container>
  );
}
