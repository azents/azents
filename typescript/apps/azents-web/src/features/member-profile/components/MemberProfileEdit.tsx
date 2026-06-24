"use client";

import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  NativeSelect,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCheck,
  IconLanguage,
  IconUser,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
/**
 * Member profile edit UI component.
 *
 * Provides name and locale edit form.
 */
import { useEffect, useState } from "react";
import { GitHubPATSection } from "./GitHubPATSection";
import type { MemberProfileContainerProps } from "../containers/useMemberProfileContainer";
import type { FormState } from "../types";

/** Supported locale list */
const LOCALE_OPTIONS = [
  { value: "ko-KR", label: "Korean" },
  { value: "en-US", label: "English" },
  { value: "ja-JP", label: "日本語" },
  { value: "fr-FR", label: "Français" },
];

export function MemberProfileEdit({
  handle,
  state,
  onSubmit,
  onResetForm,
}: MemberProfileContainerProps): React.ReactElement {
  const t = useTranslations("memberProfile");

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
            <ProfileForm
              name={state.profile.name}
              locale={state.profile.locale}
              formState={state.formState}
              onSubmit={onSubmit}
              onResetForm={onResetForm}
            />
          </Paper>
          <GitHubPATSection handle={handle} />
        </Container>
      );
  }
}

interface ProfileFormProps {
  name: string;
  locale: string;
  formState: FormState;
  onSubmit: (name: string, locale: string) => void;
  onResetForm: () => void;
}

/** Profile edit form */
function ProfileForm({
  name: initialName,
  locale: initialLocale,
  formState,
  onSubmit,
  onResetForm,
}: ProfileFormProps): React.ReactElement {
  const t = useTranslations("memberProfile");
  const [name, setName] = useState(initialName);
  const [locale, setLocale] = useState(initialLocale);
  const [nameError, setNameError] = useState<string | null>(null);

  // Synchronize form values when server data updates
  useEffect(() => {
    setName(initialName);
    setLocale(initialLocale);
  }, [initialName, initialLocale]);

  // Reset notification after a short time on success
  useEffect(() => {
    if (formState.type === "SUCCESS") {
      const timer = setTimeout(onResetForm, 3000);
      return () => clearTimeout(timer);
    }
  }, [formState.type, onResetForm]);

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();

    const trimmedName = name.trim();
    if (trimmedName.length === 0) {
      setNameError(t("nameRequired"));
      return;
    }

    setNameError(null);
    onSubmit(trimmedName, locale);
  };

  const isSubmitting = formState.type === "SUBMITTING";

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        {formState.type === "SUCCESS" && (
          <Alert icon={<IconCheck size={16} />} color="green">
            {t("updateSuccess")}
          </Alert>
        )}
        {formState.type === "ERROR" && (
          <Alert icon={<IconAlertCircle size={16} />} color="red">
            {formState.message}
          </Alert>
        )}

        <TextInput
          label={t("nameLabel")}
          placeholder={t("namePlaceholder")}
          leftSection={<IconUser size={16} />}
          value={name}
          onChange={(e) => {
            setName(e.currentTarget.value);
            if (nameError) {
              setNameError(null);
            }
          }}
          error={nameError}
          disabled={isSubmitting}
        />

        <NativeSelect
          label={t("localeLabel")}
          leftSection={<IconLanguage size={16} />}
          data={LOCALE_OPTIONS}
          value={locale}
          onChange={(e) => setLocale(e.currentTarget.value)}
          disabled={isSubmitting}
        />

        <Button type="submit" loading={isSubmitting}>
          {t("submit")}
        </Button>
      </Stack>
    </form>
  );
}
