"use client";

/**
 * Account settings page UI component.
 *
 * Displays user email and join date. Layout only, planned for future expansion.
 */
import {
  Center,
  Container,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconCalendar, IconMail } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { AccountContainerProps } from "../containers/useAccountContainer";

export function Account({ state }: AccountContainerProps): React.ReactElement {
  const t = useTranslations("account");

  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader />
        </Center>
      );
    case "ERROR":
      return (
        <Center py="xl">
          <Text c="red">{state.message}</Text>
        </Center>
      );
    case "LOADED":
      return (
        <Container size="sm" py="xl">
          <Title order={2} mb="lg">
            {t("headline")}
          </Title>
          <Paper withBorder p="lg" radius="md">
            <Stack gap="md">
              <AccountField
                icon={<IconMail size={20} />}
                label={t("email")}
                value={state.email}
              />
              <AccountField
                icon={<IconCalendar size={20} />}
                label={t("createdAt")}
                value={state.createdAt.toLocaleDateString()}
              />
            </Stack>
          </Paper>
        </Container>
      );
  }
}

interface AccountFieldProps {
  icon: React.ReactElement;
  label: string;
  value: string;
}

/** Account settings field (icon + label + value) */
function AccountField({
  icon,
  label,
  value,
}: AccountFieldProps): React.ReactElement {
  return (
    <Stack gap={4}>
      <Text
        size="sm"
        c="dimmed"
        style={{ display: "flex", alignItems: "center", gap: 6 }}
      >
        {icon}
        {label}
      </Text>
      <Text size="md">{value}</Text>
    </Stack>
  );
}
