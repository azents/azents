"use client";
import { useState } from "react";
import { projectAwsFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type { AwsConfigFieldsProps, ToolkitConfigFieldsInput } from "../types";
export function useAwsConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): AwsConfigFieldsProps {
  const [showKeyInput, setShowKeyInput] = useState(!props.hasCredentials);
  return {
    ...props,
    view: projectAwsFields(props.config, props.credentials),
    ...useProviderConnectionTest(props, "aws"),
    showKeyInput,
    onShowKeyInput: () => setShowKeyInput(true),
  };
}
