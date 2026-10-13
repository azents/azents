"use client";
import { projectNotionFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  NotionConfigFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useNotionConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): NotionConfigFieldsProps {
  return {
    ...props,
    view: projectNotionFields(props.config),
    ...useProviderConnectionTest(props, "notion"),
  };
}
