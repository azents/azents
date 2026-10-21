"use client";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import type { ProviderFormProps } from "../components/IntegrationFormModal";
interface ApiKeyFormValues {
  apiKey: string;
}

export interface ApiKeyFormViewProps {
  isCreate: ProviderFormProps["isCreate"];
  isSubmitting: ProviderFormProps["isSubmitting"];
  onClose: ProviderFormProps["onClose"];
  t: ReturnType<typeof useTranslations<"workspace.llmSettings">>;
  form: ReturnType<typeof useForm<ApiKeyFormValues>>;
  handleSubmit: (values: ApiKeyFormValues) => void;
}
export function useApiKeyFormController({
  name,
  provider,
  isCreate,
  isSubmitting,
  onCreate,
  onUpdate,
  onClose,
}: ProviderFormProps): ApiKeyFormViewProps {
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
  return { isCreate, isSubmitting, onClose, t, form, handleSubmit };
}
