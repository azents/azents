"use client";
import { useState } from "react";
import { projectGoogleAnalyticsFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import { useServiceAccountKeyUpload } from "./useServiceAccountKeyUpload";
import type {
  GoogleAnalyticsConfigFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useGoogleAnalyticsConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): GoogleAnalyticsConfigFieldsProps {
  const [showKeyInput, setShowKeyInput] = useState(!props.hasCredentials);
  return {
    ...props,
    view: projectGoogleAnalyticsFields(props.config, props.credentials),
    ...useServiceAccountKeyUpload(props.onCredentialsChange),
    ...useProviderConnectionTest(props, "google_analytics"),
    showKeyInput,
    onShowKeyInput: () => setShowKeyInput(true),
  };
}
