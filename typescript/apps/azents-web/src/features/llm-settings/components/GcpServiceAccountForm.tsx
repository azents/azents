"use client";

/**
 * Google Vertex AI provider form.
 *
 * Project ID, Region, Service Account JSON input form.
 * Config (projectId, region) is pre-filled on EDIT; Secret (serviceAccountJson) is empty.
 */

import {
  Autocomplete,
  Button,
  Group,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { GCP_REGIONS } from "../constants/regions";
import type { ProviderFormProps } from "./IntegrationFormModal";

interface GcpFormValues {
  projectId: string;
  region: string;
  serviceAccountJson: string;
}

export function GcpServiceAccountForm({
  name,
  provider,
  integration,
  isCreate,
  isSubmitting,
  onCreate,
  onUpdate,
  onClose,
}: ProviderFormProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");

  const config = integration?.config;
  const form = useForm<GcpFormValues>({
    mode: "controlled",
    initialValues: {
      projectId:
        config?.type === "gcp_service_account" ? config.project_id : "",
      region: config?.type === "gcp_service_account" ? config.region : "",
      serviceAccountJson: "",
    },
  });

  function handleSubmit(values: GcpFormValues): void {
    if (isCreate) {
      if (
        !provider ||
        !values.projectId ||
        !values.region ||
        !values.serviceAccountJson
      ) {
        return;
      }
      onCreate({
        provider,
        ...(name ? { name } : {}),
        secrets: {
          type: "gcp_service_account",
          service_account_json: values.serviceAccountJson,
        },
        config: {
          type: "gcp_service_account",
          project_id: values.projectId,
          region: values.region,
        },
      });
    } else {
      const data: Parameters<ProviderFormProps["onUpdate"]>[0] = {};
      if (name) {
        data.name = name;
      }
      if (values.serviceAccountJson) {
        data.secrets = {
          type: "gcp_service_account",
          service_account_json: values.serviceAccountJson,
        };
      }
      if (values.projectId && values.region) {
        data.config = {
          type: "gcp_service_account",
          project_id: values.projectId,
          region: values.region,
        };
      }
      onUpdate(data);
    }
  }

  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="md">
        <TextInput
          label={t("projectIdLabel")}
          {...form.getInputProps("projectId")}
          required={isCreate}
          autoCapitalize="none"
        />
        <Autocomplete
          label={t("regionLabel")}
          placeholder={t("regionPlaceholder")}
          data={GCP_REGIONS}
          {...form.getInputProps("region")}
          required={isCreate}
          autoCapitalize="none"
        />
        <Textarea
          label={t("serviceAccountJsonLabel")}
          placeholder={isCreate ? "" : t("credentialsPlaceholderEdit")}
          {...form.getInputProps("serviceAccountJson")}
          required={isCreate}
          minRows={4}
          autosize
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
