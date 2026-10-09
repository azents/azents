"use client";
import { useState } from "react";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import { useServiceAccountKeyUpload } from "./useServiceAccountKeyUpload";
import type {
  ServiceAccountProviderFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useGcpConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): ServiceAccountProviderFieldsProps {
  const [showKeyInput, setShowKeyInput] = useState(!props.hasCredentials);
  return {
    ...props,
    ...useServiceAccountKeyUpload(props.onCredentialsChange),
    ...useProviderConnectionTest(props, "gcp"),
    showKeyInput,
    onShowKeyInput: () => setShowKeyInput(true),
  };
}
