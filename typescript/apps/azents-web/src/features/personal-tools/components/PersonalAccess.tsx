"use client";

import {
  Alert,
  Anchor,
  Box,
  Button,
  Center,
  Container,
  Divider,
  Group,
  Loader,
  Paper,
  Radio,
  rem,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconCheck,
  IconSearch,
  IconShieldCheck,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentAvatar } from "@/shared/agent-session/AgentAvatar";
import type { PersonalAccessProps } from "../types";

export function PersonalAccess({
  state,
  handle,
  target,
  setupHref,
  search,
  dirty,
  write,
  onSearch,
  onMode,
  onToggle,
  onSave,
  onCancel,
  onReload,
}: PersonalAccessProps): React.ReactElement {
  const t = useTranslations("account.personalTools");
  const base = `/w/${encodeURIComponent(handle)}/personal-tools`;
  if (state.type === "LOADING") {
    return (
      <Center p="xl">
        <Loader aria-label={t("loading")} />
      </Center>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Container py="xl">
        <Alert color="red" title={t("loadError")}>
          <Button onClick={onReload} variant="subtle">
            {t("reload")}
          </Button>
        </Alert>
      </Container>
    );
  }
  const saving = write.type === "SAVING";
  const items = state.groups.flatMap((group) => group.items);
  return (
    <Container
      size="sm"
      w="100%"
      py={{ base: "md", sm: "xl" }}
      h={
        target === "connection"
          ? "calc(100dvh - var(--app-shell-header-offset, 0rem))"
          : "100%"
      }
      mih={0}
      style={{ flex: 1, display: "flex", flexDirection: "column" }}
    >
      <Stack gap="md" mih={0} style={{ flex: 1 }}>
        {target === "connection" && (
          <Anchor component={Link} href={base} size="sm">
            <Group gap="xs">
              <IconArrowLeft size={16} />
              {t("title")}
            </Group>
          </Anchor>
        )}
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <ThemeIcon variant="light" size="lg" radius="md">
            <IconShieldCheck size={22} />
          </ThemeIcon>
          <Stack gap={rem(4)} style={{ minWidth: 0 }}>
            <Title order={2} size="h3">
              {t(target === "agent" ? "agentAccessTitle" : "accessTitle")}
            </Title>
            <Text fw={500} style={{ overflowWrap: "anywhere" }}>
              {state.subject}
            </Text>
            <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
              {state.account}
            </Text>
          </Stack>
        </Group>
        <Text size="sm" c="dimmed">
          {t(target === "agent" ? "agentScope" : "connectionScope")}
        </Text>
        {write.type === "ERROR" && (
          <Alert
            color="red"
            title={t(write.conflict ? "conflict" : "saveError")}
          >
            <Stack gap="xs">
              <Text size="sm">{t("draftRetained")}</Text>
              <Button
                variant="light"
                size="xs"
                onClick={onReload}
                style={{ alignSelf: "flex-start" }}
              >
                {t("reload")}
              </Button>
            </Stack>
          </Alert>
        )}
        {write.type === "SAVED" && (
          <Alert color="green" role="status">
            {t("saved")}
          </Alert>
        )}
        {state.mode !== null && (
          <Paper withBorder radius="md" p="md">
            <Radio.Group
              label={t("policy")}
              value={state.mode}
              onChange={onMode}
            >
              <Stack gap="sm" mt="sm">
                <Radio value="all" label={t("allowAll")} disabled={saving} />
                <Radio
                  value="selected"
                  label={t("selected")}
                  disabled={saving}
                />
              </Stack>
            </Radio.Group>
            {state.mode === "all" && (
              <Text size="xs" c="dimmed" mt="md">
                {t("allExplanation")}
              </Text>
            )}
          </Paper>
        )}
        {state.firstRestriction && (
          <Alert color="yellow" variant="light">
            {t("firstRestriction")}
          </Alert>
        )}
        {state.empty ? (
          <Paper withBorder radius="md" p="xl">
            <Stack align="flex-start" gap="md">
              <Text c="dimmed" size="sm">
                {t(target === "agent" ? "empty" : "noAgents")}
              </Text>
              {target === "agent" && (
                <Button component={Link} href={setupHref ?? `${base}/new`}>
                  {t("add")}
                </Button>
              )}
            </Stack>
          </Paper>
        ) : (
          <Stack gap="sm" mih={0} style={{ flex: 1 }}>
            <TextInput
              aria-label={t(
                target === "agent" ? "searchTools" : "searchAgents",
              )}
              placeholder={t(
                target === "agent" ? "searchTools" : "searchAgents",
              )}
              leftSection={<IconSearch size={16} />}
              value={search}
              onChange={(event) => onSearch(event.currentTarget.value)}
            />
            <Paper
              withBorder
              radius="md"
              mih={0}
              style={{ overflowY: "auto", flex: "0 1 auto" }}
            >
              {items.length === 0 && (
                <Text p="lg" c="dimmed" size="sm">
                  {t("noMatches")}
                </Text>
              )}
              {items.map((item, index) => (
                <Box key={item.id}>
                  {index > 0 && <Divider />}
                  <UnstyledButton
                    type="button"
                    role="checkbox"
                    aria-label={item.name}
                    aria-checked={item.allowed}
                    disabled={saving}
                    onClick={() => onToggle(item.id, !item.allowed)}
                    w="100%"
                    p="md"
                    style={{
                      display: "block",
                      textAlign: "left",
                      background: item.allowed
                        ? "var(--mantine-color-default-hover)"
                        : "var(--mantine-color-body)",
                    }}
                  >
                    <Group gap="md" wrap="nowrap" justify="space-between">
                      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                        {target === "connection" && (
                          <Box aria-hidden="true">
                            <AgentAvatar
                              name={item.name}
                              avatar={item.avatar}
                              size="md"
                            />
                          </Box>
                        )}
                        <Stack gap={rem(2)} style={{ minWidth: 0 }}>
                          <Text
                            size="sm"
                            fw={500}
                            style={{ overflowWrap: "anywhere" }}
                          >
                            {item.name}
                          </Text>
                          {item.detail && (
                            <Text size="xs" c="dimmed">
                              {item.detail}
                            </Text>
                          )}
                        </Stack>
                      </Group>
                      <Box w={rem(20)} h={rem(20)} style={{ flexShrink: 0 }}>
                        {item.allowed && (
                          <IconCheck
                            aria-hidden="true"
                            size={20}
                            color="var(--mantine-color-blue-6)"
                          />
                        )}
                      </Box>
                    </Group>
                  </UnstyledButton>
                </Box>
              ))}
            </Paper>
          </Stack>
        )}
        <Box
          py="sm"
          bg="var(--mantine-color-body)"
          style={{
            position: "sticky",
            bottom: 0,
            zIndex: 2,
            flexShrink: 0,
            borderTop: `${rem(1)} solid var(--mantine-color-default-border)`,
          }}
        >
          <Group justify="space-between" gap="sm" wrap="wrap">
            <Text size="xs" c={dirty ? "blue" : "dimmed"} role="status">
              {dirty ? t("unsaved") : t("unchanged")}
            </Text>
            <Group gap="xs">
              <Button
                variant="default"
                onClick={onCancel}
                disabled={!dirty || saving}
              >
                {t("cancel")}
              </Button>
              <Button
                onClick={() => {
                  void onSave();
                }}
                loading={saving}
                disabled={!dirty}
              >
                {t("save")}
              </Button>
            </Group>
          </Group>
        </Box>
        {target === "agent" && (
          <Anchor component={Link} href={base} size="sm">
            {t("manage")}
          </Anchor>
        )}
      </Stack>
    </Container>
  );
}
