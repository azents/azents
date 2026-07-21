"use client";

import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconCheck, IconUser } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
/**
 * Member profile edit UI component.
 *
 * Provides name edit form.
 */
import { useEffect, useState } from "react";
import type { MemberProfileContainerProps } from "../containers/useMemberProfileContainer";
import type { FormState } from "../types";

export function MemberProfileEdit({
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
              formState={state.formState}
              onSubmit={onSubmit}
              onResetForm={onResetForm}
            />
          </Paper>
        </Container>
      );
  }
}

interface ProfileFormProps {
  name: string;
  formState: FormState;
  onSubmit: (name: string) => void;
  onResetForm: () => void;
}

/** Profile edit form */
function ProfileForm({
  name: initialName,
  formState,
  onSubmit,
  onResetForm,
}: ProfileFormProps): React.ReactElement {
  const t = useTranslations("memberProfile");
  const [name, setName] = useState(initialName);
  const [nameError, setNameError] = useState<string | null>(null);

  // Synchronize form values when server data updates
  useEffect(() => {
    setName(initialName);
  }, [initialName]);

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
    onSubmit(trimmedName);
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

        <Button type="submit" loading={isSubmitting}>
          {t("submit")}
        </Button>
      </Stack>
    </form>
  );
}
