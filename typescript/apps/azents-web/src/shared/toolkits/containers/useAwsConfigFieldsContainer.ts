"use client";
import { useState } from "react";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  CredentialProviderFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useAwsConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): CredentialProviderFieldsProps {
  const [showKeyInput, setShowKeyInput] = useState(!props.hasCredentials);
  return {
    ...props,
    ...useProviderConnectionTest(props, "aws"),
    showKeyInput,
    onShowKeyInput: () => setShowKeyInput(true),
  };
}
