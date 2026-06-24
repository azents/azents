"use client";

/**
 * AWS Bedrock provider form.
 *
 * Access Key ID, Secret Access Key, Region input form.
 * Config (accessKeyId, region) is pre-filled on EDIT; Secret (secretAccessKey) is empty.
 */

import { Autocomplete, Button, Group, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { AWS_REGIONS } from "../constants/regions";
import type { ProviderFormProps } from "./IntegrationFormModal";

interface AwsFormValues {
  accessKeyId: string;
  secretAccessKey: string;
  region: string;
  roleArn: string;
}

export function AwsCredentialsForm({
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
  const awsConfig = config?.type === "aws_credentials" ? config : null;
  const form = useForm<AwsFormValues>({
    mode: "controlled",
    initialValues: {
      accessKeyId: awsConfig ? awsConfig.access_key_id : "",
      secretAccessKey: "",
      region: awsConfig ? awsConfig.region : "",
      roleArn: awsConfig?.role_arn ?? "",
    },
  });

  function handleSubmit(values: AwsFormValues): void {
    if (isCreate) {
      if (
        !provider ||
        !values.accessKeyId ||
        !values.secretAccessKey ||
        !values.region
      ) {
        return;
      }
      onCreate({
        provider,
        ...(name ? { name } : {}),
        secrets: {
          type: "aws_credentials",
          secret_access_key: values.secretAccessKey,
        },
        config: {
          type: "aws_credentials",
          access_key_id: values.accessKeyId,
          region: values.region,
          ...(values.roleArn ? { role_arn: values.roleArn } : {}),
        },
      });
    } else {
      const data: Parameters<ProviderFormProps["onUpdate"]>[0] = {};
      if (name) {
        data.name = name;
      }
      if (values.secretAccessKey) {
        data.secrets = {
          type: "aws_credentials",
          secret_access_key: values.secretAccessKey,
        };
      }
      if (values.accessKeyId && values.region) {
        data.config = {
          type: "aws_credentials",
          access_key_id: values.accessKeyId,
          region: values.region,
          ...(values.roleArn ? { role_arn: values.roleArn } : {}),
        };
      }
      onUpdate(data);
    }
  }

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
