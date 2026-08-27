import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ModelCatalogPicker } from "./ModelCatalogPicker";
import type {
  ModelCatalogAttemptState,
  ModelCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "../model-selection";
import type { ModelCatalogPickerState } from "./ModelCatalogPicker";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};

const integrations: ProviderIntegrationOption[] = [
  {
    value: "integration-bedrock",
    label: "AWS Bedrock · aws_bedrock",
    provider: "aws_bedrock",
    integration: {
      id: "integration-bedrock",
      provider: "aws_bedrock",
      name: "AWS Bedrock",
      config: {
        type: "aws_credentials",
        access_key_id: "AKIA...",
        region: "us-west-2",
      },
      enabled: true,
      created_at: "2026-06-21T00:00:00Z",
      updated_at: "2026-06-21T00:00:00Z",
    },
    disabled: false,
  },
];

const models: SelectableModelCandidate[] = [
  {
    provider: "aws_bedrock",
    model_identifier: "anthropic.claude-sonnet-4-5-v1:0",
    model_display_name: "Claude Sonnet 4.5",
    normalized_capabilities: {
      reasoning: { supported: true, effort_levels: ["low", "high"] },
      built_in_tools: { supported: ["web_search"] },
      context_window: {
        default_input_tokens: 272_000,
        max_input_tokens: 872_000,
        max_output_tokens: 64_000,
      },
      modalities: { input: ["text"], output: ["text"] },
      tool_calling: { supported: true },
      parameters: {},
      compatibility: {},
    },
  },
];

const failedAttempt: ModelCatalogAttemptState = {
  status: "failed",
  started_at: "2026-08-27T09:00:00Z",
  finished_at: "2026-08-27T09:00:04Z",
  failure_code: "provider_unavailable",
  failure_message: "The provider catalog is temporarily unavailable.",
  action_hint: "Retry after confirming provider credentials.",
  fetched_count: 0,
  matched_count: 0,
  skipped_count: 0,
  hidden_count: 0,
};

const failedCatalog: ModelCatalogState = {
  catalogId: "catalog-1",
  catalogScope: "integration",
  currentSnapshotId: null,
  currentSnapshotCreatedAt: null,
  latestAttempt: failedAttempt,
  stale: false,
  syncAvailableAt: null,
  automaticRetryBlocked: false,
  total: 0,
  loaded: 0,
};

const readyState: ModelCatalogPickerState = {
  selectedIntegration: integrations[0] ?? null,
  catalog: {
    catalogId: "catalog-1",
    catalogScope: "integration",
    currentSnapshotId: "snapshot-1",
    currentSnapshotCreatedAt: "2026-08-27T09:00:00Z",
    latestAttempt: {
      status: "succeeded",
      started_at: "2026-08-27T08:59:30Z",
      finished_at: "2026-08-27T09:00:00Z",
      failure_code: null,
      failure_message: null,
      action_hint: null,
      fetched_count: 1,
      matched_count: 1,
      skipped_count: 0,
      hidden_count: 0,
    },
    stale: false,
    syncAvailableAt: null,
    automaticRetryBlocked: false,
    total: 1,
    loaded: 1,
  },
  models,
  search: "",
  loading: false,
  fetching: false,
  hasLoadedPage: true,
  hasNextPage: false,
  syncSupported: true,
  canSync: true,
  syncRunning: false,
  syncPending: false,
  syncThrottled: false,
  syncAvailableAt: null,
  syncError: null,
  ui: { type: "READY" },
};

const meta = {
  component: ModelCatalogPicker,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(900)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    opened: true,
    title: "Select model",
    integrations,
    selectedIntegrationId: "integration-bedrock",
    selectedValue: null,
    state: readyState,
    onClose: noop,
    onSelectIntegration: noop,
    onSelectModel: noop,
    onSearchChange: noop,
    onSyncCatalog: noop,
  },
} satisfies Meta<typeof ModelCatalogPicker>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ReadyWithContextRange = {} satisfies Story;

export const NoIntegrationSelected = {
  args: {
    selectedIntegrationId: null,
    state: {
      ...readyState,
      selectedIntegration: null,
      catalog: null,
      models: [],
      hasLoadedPage: false,
      syncSupported: false,
      canSync: false,
      ui: { type: "NO_INTEGRATION" },
    },
  },
} satisfies Story;

export const Loading = {
  args: {
    state: {
      ...readyState,
      catalog: null,
      models: [],
      loading: true,
      hasLoadedPage: false,
      canSync: false,
      ui: { type: "LOADING_STATUS" },
    },
  },
} satisfies Story;

export const FailedWithoutSnapshot = {
  args: {
    state: {
      ...readyState,
      catalog: failedCatalog,
      models: [],
      canSync: true,
      ui: {
        type: "FAILED_WITHOUT_SNAPSHOT",
        attempt: failedAttempt,
      },
    },
  },
} satisfies Story;
