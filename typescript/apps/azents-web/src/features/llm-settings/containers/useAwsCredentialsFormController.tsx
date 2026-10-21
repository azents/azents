"use client";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import type { ProviderFormProps } from "../components/IntegrationFormModal";
interface AwsFormValues {
  accessKeyId: string;
  secretAccessKey: string;
  region: string;
  roleArn: string;
}

export interface AwsCredentialsFormViewProps {
  isCreate: ProviderFormProps["isCreate"];
  isSubmitting: ProviderFormProps["isSubmitting"];
  onClose: ProviderFormProps["onClose"];
  t: ReturnType<typeof useTranslations<"workspace.llmSettings">>;
  form: ReturnType<typeof useForm<AwsFormValues>>;
  handleSubmit: (values: AwsFormValues) => void;
}
export function useAwsCredentialsFormController({
  name,
  provider,
  integration,
  isCreate,
  isSubmitting,
  onCreate,
  onUpdate,
  onClose,
}: ProviderFormProps): AwsCredentialsFormViewProps {
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
  return { isCreate, isSubmitting, onClose, t, form, handleSubmit };
}
