"use client";
import { useState } from "react";
import { projectGcpFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import { useServiceAccountKeyUpload } from "./useServiceAccountKeyUpload";
import type { GcpConfigFieldsProps, ToolkitConfigFieldsInput } from "../types";
export function useGcpConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): GcpConfigFieldsProps {
  const [showKeyInput, setShowKeyInput] = useState(!props.hasCredentials);
  return {
    ...props,
    view: projectGcpFields(props.config, props.credentials),
    ...useServiceAccountKeyUpload(props.onCredentialsChange),
    ...useProviderConnectionTest(props, "gcp"),
    showKeyInput,
    onShowKeyInput: () => setShowKeyInput(true),
  };
}
