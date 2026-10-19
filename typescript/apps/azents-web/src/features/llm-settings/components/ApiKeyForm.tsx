"use client";
import { Button, Group, Stack, TextInput } from "@mantine/core";
import { useApiKeyFormController } from "../containers/useApiKeyFormController";
/**
 * API Key provider form.
 *
 * Credential input form for API Key-based providers such as OpenAI, Anthropic, Google Gemini.
 */
import type { ApiKeyFormViewProps } from "../containers/useApiKeyFormController";
import type { ProviderFormProps } from "./IntegrationFormModal";

export function ApiKeyForm(props: ProviderFormProps): React.ReactElement {
  return <ApiKeyFormView {...useApiKeyFormController(props)} />;
}

export function ApiKeyFormView({
  isCreate,
  isSubmitting,
  onClose,
  t,
  form,
  handleSubmit,
}: ApiKeyFormViewProps): React.ReactElement {
  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="md">
        <TextInput
          label={t("apiKeyLabel")}
          placeholder={
            isCreate ? t("apiKeyPlaceholder") : t("credentialsPlaceholderEdit")
          }
          type="password"
          {...form.getInputProps("apiKey")}
          required={isCreate}
          autoCapitalize="none"
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button type="submit" loading={isSubmitting}>
            {isCreate ? t("create") : t("save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
