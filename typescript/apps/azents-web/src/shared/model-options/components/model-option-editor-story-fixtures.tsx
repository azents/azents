import { ModelCatalogPicker } from "./ModelCatalogPicker";
import type { ModelCatalogPickerContainerProps } from "../containers/ModelCatalogPickerContainer";
import type { ModelCatalogPickerState } from "./ModelCatalogPicker";
import type { ReactNode } from "react";

/** Static picker adapter: editor stories never mount the API-backed picker. */
export function renderStaticModelPicker(
  props: ModelCatalogPickerContainerProps,
): ReactNode {
  const selectedIntegration =
    props.integrations.find(
      (item) => item.value === props.selectedIntegrationId,
    ) ?? null;
  const state: ModelCatalogPickerState = {
    selectedIntegration,
    catalog: null,
    models: [
      {
        provider: selectedIntegration?.provider ?? "openai",
        model_identifier: "story-model",
        model_display_name: "Story model",
        normalized_capabilities: {
          reasoning: { supported: false, effort_levels: [] },
          built_in_tools: { supported: [] },
          context_window: {
            max_input_tokens: 128_000,
            max_output_tokens: null,
          },
          modalities: { input: ["text"], output: ["text"] },
          tool_calling: { supported: true },
          parameters: {},
          compatibility: {},
        },
      },
    ],
    search: "",
    loading: false,
    fetching: false,
    hasLoadedPage: true,
    hasNextPage: false,
    syncSupported: false,
    canSync: false,
    syncRunning: false,
    syncPending: false,
    syncThrottled: false,
    syncAvailableAt: null,
    syncError: null,
    ui: { type: "READY" },
  };
  return (
    <ModelCatalogPicker
      {...props}
      state={state}
      onSearchChange={() => {}}
      onSyncCatalog={() => {}}
    />
  );
}
