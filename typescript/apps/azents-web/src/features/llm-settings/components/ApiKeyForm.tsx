"use client";

/**
 * API Key provider form.
 *
 * Credential input form for API Key-based providers such as OpenAI, Anthropic, Google Gemini.
 */

import { Button, Group, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import type { ProviderFormProps } from "./IntegrationFormModal";

interface ApiKeyFormValues {
  apiKey: string;
}

export function ApiKeyForm({
  name,
  provider,
  isCreate,
  isSubmitting,
  onCreate,
  onUpdate,
  onClose,
}: ProviderFormProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");

  const form = useForm<ApiKeyFormValues>({
    mode: "controlled",
    initialValues: { apiKey: "" },
  });

  function handleSubmit(values: ApiKeyFormValues): void {
    if (isCreate) {
      if (!provider || !values.apiKey) {
        return;
      }
      onCreate({
        provider,
        ...(name ? { name } : {}),
        secrets: { type: "api_key", api_key: values.apiKey },
        config: null,
      });
    } else {
      const data: Parameters<ProviderFormProps["onUpdate"]>[0] = {};
      if (name) {
        data.name = name;
      }
      if (values.apiKey) {
        data.secrets = { type: "api_key", api_key: values.apiKey };
      }
      onUpdate(data);
    }
  }

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
