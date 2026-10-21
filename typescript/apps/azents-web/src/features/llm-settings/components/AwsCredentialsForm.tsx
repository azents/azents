"use client";
import { Autocomplete, Button, Group, Stack, TextInput } from "@mantine/core";
import { AWS_REGIONS } from "../constants/regions";
/**
 * AWS Bedrock provider form.
 *
 * Access Key ID, Secret Access Key, Region input form.
 * Config (accessKeyId, region) is pre-filled on EDIT; Secret (secretAccessKey) is empty.
 */
import { useAwsCredentialsFormController } from "../containers/useAwsCredentialsFormController";
import type { AwsCredentialsFormViewProps } from "../containers/useAwsCredentialsFormController";
import type { ProviderFormProps } from "./IntegrationFormModal";

export function AwsCredentialsForm(
  props: ProviderFormProps,
): React.ReactElement {
  return <AwsCredentialsFormView {...useAwsCredentialsFormController(props)} />;
}

export function AwsCredentialsFormView({
  isCreate,
  isSubmitting,
  onClose,
  t,
  form,
  handleSubmit,
}: AwsCredentialsFormViewProps): React.ReactElement {
  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="md">
        <TextInput
          label={t("accessKeyIdLabel")}
          {...form.getInputProps("accessKeyId")}
          required={isCreate}
          autoCapitalize="none"
        />
        <TextInput
          label={t("secretAccessKeyLabel")}
          placeholder={isCreate ? "" : t("credentialsPlaceholderEdit")}
          type="password"
          {...form.getInputProps("secretAccessKey")}
          required={isCreate}
        />
        <Autocomplete
          label={t("regionLabel")}
          placeholder={t("regionPlaceholder")}
          data={AWS_REGIONS}
          {...form.getInputProps("region")}
          required={isCreate}
          autoCapitalize="none"
        />
        <TextInput
          label={t("roleArnLabel")}
          placeholder={t("roleArnPlaceholder")}
          {...form.getInputProps("roleArn")}
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
