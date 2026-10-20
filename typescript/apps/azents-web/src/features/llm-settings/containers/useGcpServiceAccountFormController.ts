"use client";

import { useForm } from "@mantine/form";
import type { ProviderFormProps } from "../components/IntegrationFormModal";
import type { UseFormReturnType } from "@mantine/form";

export interface GcpFormValues {
  projectId: string;
  region: string;
  serviceAccountJson: string;
}
export interface GcpServiceAccountFormOutput extends ProviderFormProps {
  projectIdInput: ReturnType<UseFormReturnType<GcpFormValues>["getInputProps"]>;
  regionInput: ReturnType<UseFormReturnType<GcpFormValues>["getInputProps"]>;
  serviceAccountInput: ReturnType<
    UseFormReturnType<GcpFormValues>["getInputProps"]
  >;
  handleSubmit: (event?: React.FormEvent<HTMLFormElement>) => void;
}
export function useGcpServiceAccountFormController(
  props: ProviderFormProps,
): GcpServiceAccountFormOutput {
  const { name, provider, integration, isCreate, onCreate, onUpdate } = props;
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
  return {
    ...props,
    projectIdInput: form.getInputProps("projectId"),
    regionInput: form.getInputProps("region"),
    serviceAccountInput: form.getInputProps("serviceAccountJson"),
    handleSubmit: form.onSubmit(handleSubmit),
  };
}
