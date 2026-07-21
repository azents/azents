"use client";

/**
 * Account settings page UI component.
 *
 * Displays user email and join date. Layout only, planned for future expansion.
 */
import {
  Button,
  Center,
  Container,
  Loader,
  NativeSelect,
  Paper,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconCalendar, IconLanguage, IconMail } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import {
  DEFAULT_LOCALE,
  isSupportedLocale,
  LOCALE_DISPLAY_NAMES,
  SUPPORTED_LOCALES,
  type SupportedLocale,
} from "@/shared/lib/locale";
import type { AccountContainerProps } from "../containers/useAccountContainer";

export function Account({
  state,
  onSubmit,
}: AccountContainerProps): React.ReactElement {
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
              <AccountLocaleForm locale={state.locale} onSubmit={onSubmit} />
            </Stack>
          </Paper>
        </Container>
      );
  }
}

interface AccountLocaleFormProps {
  locale: string;
  onSubmit: (locale: SupportedLocale) => void;
}

function AccountLocaleForm({
  locale: initialLocale,
  onSubmit,
}: AccountLocaleFormProps): React.ReactElement {
  const t = useTranslations("account");
  const [locale, setLocale] = useState<SupportedLocale>(
    isSupportedLocale(initialLocale) ? initialLocale : DEFAULT_LOCALE,
  );

  useEffect(() => {
    if (isSupportedLocale(initialLocale)) {
      setLocale(initialLocale);
    }
  }, [initialLocale]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(locale);
      }}
    >
      <Stack gap="sm">
        <NativeSelect
          label={t("localeLabel")}
          leftSection={<IconLanguage size={16} />}
          data={SUPPORTED_LOCALES.map((value) => ({
            value,
            label: LOCALE_DISPLAY_NAMES[value],
          }))}
          value={locale}
          onChange={(event) => {
            const value = event.currentTarget.value;
            if (isSupportedLocale(value)) {
              setLocale(value);
            }
          }}
        />
        <Button type="submit">{t("saveLocale")}</Button>
      </Stack>
    </form>
  );
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
