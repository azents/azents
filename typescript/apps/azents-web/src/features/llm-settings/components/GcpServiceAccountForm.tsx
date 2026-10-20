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
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GCP_REGIONS } from "../constants/regions";
import { useGcpServiceAccountFormController } from "../containers/useGcpServiceAccountFormController";
import type { GcpServiceAccountFormOutput } from "../containers/useGcpServiceAccountFormController";

export const GcpServiceAccountForm = createReactContainer(
  "GcpServiceAccountForm",
  useGcpServiceAccountFormController,
  GcpServiceAccountFormView,
);

export function GcpServiceAccountFormView({
  isCreate,
  isSubmitting,
  onClose,
  projectIdInput,
  regionInput,
  serviceAccountInput,
  handleSubmit,
}: GcpServiceAccountFormOutput): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        <TextInput
          label={t("projectIdLabel")}
          {...projectIdInput}
          required={isCreate}
          autoCapitalize="none"
        />
        <Autocomplete
          label={t("regionLabel")}
          placeholder={t("regionPlaceholder")}
          data={GCP_REGIONS}
          {...regionInput}
          required={isCreate}
          autoCapitalize="none"
        />
        <Textarea
          label={t("serviceAccountJsonLabel")}
          placeholder={isCreate ? "" : t("credentialsPlaceholderEdit")}
          {...serviceAccountInput}
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
