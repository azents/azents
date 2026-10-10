"use client";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  SimpleProviderFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useSentryConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): SimpleProviderFieldsProps {
  return { ...props, ...useProviderConnectionTest(props, "sentry") };
}
