"use client";
import { projectSentryFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  SentryConfigFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useSentryConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): SentryConfigFieldsProps {
  return {
    ...props,
    view: projectSentryFields(props.config),
    ...useProviderConnectionTest(props, "sentry"),
  };
}
