"use client";

/** Workspace default model selection settings card */

import { Alert, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { ModelCatalogPicker } from "@/features/agents/components/ModelCatalogPicker";
import {
  formatModelSelectionSummary,
  modelSelectionProviderValue,
  modelSelectionValue,
} from "@/features/agents/model-selection";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "@/features/agents/model-selection";
import type { WorkspaceModelSettingsResponse } from "@azents/public-client";

interface WorkspaceModelSettingsFormValues {
  defaultModelProviderIntegrationId: string | null;
  defaultModelValue: string | null;
  defaultLightweightModelProviderIntegrationId: string | null;
  defaultLightweightModelValue: string | null;
}

export interface WorkspaceModelSettingsCardProps {
  settings: WorkspaceModelSettingsResponse | null;
  handle: string;
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  canManage: boolean;
  submitting: boolean;
  error: string | null;
  onSyncCatalog: (integrationId: string) => void;
  onSubmit: (values: WorkspaceModelSettingsFormValues) => void;
}

export function WorkspaceModelSettingsCard({
  settings,
  handle,
  providerOptions,
  modelOptions,
  canManage,
  submitting,
  error,
  onSyncCatalog,
  onSubmit,
}: WorkspaceModelSettingsCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.modelSelection");
  const [mainPickerOpen, setMainPickerOpen] = useState(false);
  const [lightweightPickerOpen, setLightweightPickerOpen] = useState(false);
  const [mainPreview, setMainPreview] =
    useState<SelectableModelCandidate | null>(null);
  const [lightweightPreview, setLightweightPreview] =
    useState<SelectableModelCandidate | null>(null);
  const form = useForm<WorkspaceModelSettingsFormValues>({
    mode: "controlled",
    initialValues: {
      defaultModelProviderIntegrationId: null,
      defaultModelValue: null,
      defaultLightweightModelProviderIntegrationId: null,
      defaultLightweightModelValue: null,
    },
  });

  useEffect(() => {
    form.setValues({
      defaultModelProviderIntegrationId: modelSelectionProviderValue(
        settings?.default_model_selection,
      ),
      defaultModelValue: modelSelectionValue(settings?.default_model_selection),
      defaultLightweightModelProviderIntegrationId: modelSelectionProviderValue(
        settings?.default_lightweight_model_selection,
      ),
      defaultLightweightModelValue: modelSelectionValue(
        settings?.default_lightweight_model_selection,
      ),
    });
    setMainPreview(null);
    setLightweightPreview(null);
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Resynchronize form when server settings change.
  }, [settings]);

  const enabledProviderOptions = useMemo(
    () => providerOptions.filter((option) => !option.disabled),
    [providerOptions],
  );

  const defaultModelOptions = useMemo(
    () =>
      modelOptions.filter(
        (option) =>
          !option.disabled &&
          option.integrationId ===
            form.values.defaultModelProviderIntegrationId,
      ),
    [form.values.defaultModelProviderIntegrationId, modelOptions],
  );

  const submit = form.onSubmit((values) => {
    onSubmit(values);
  });

  return (
    <Card withBorder padding="md">
      <form onSubmit={submit}>
        <Stack gap="md">
          <ModelCatalogPicker
            opened={mainPickerOpen}
            title={t("selectWorkspaceDefaultModel")}
            handle={handle}
            integrations={enabledProviderOptions}
            selectedIntegrationId={
              form.values.defaultModelProviderIntegrationId
            }
            selectedValue={form.values.defaultModelValue}
            onClose={() => setMainPickerOpen(false)}
            onSelectIntegration={(integrationId) => {
              form.setFieldValue(
                "defaultModelProviderIntegrationId",
                integrationId,
              );
              form.setFieldValue("defaultModelValue", null);
              setMainPreview(null);
            }}
            onSelectModel={(model) => {
              const integrationId =
                form.values.defaultModelProviderIntegrationId;
              if (integrationId == null) {
                return;
              }
              form.setFieldValue(
                "defaultModelValue",
                `${integrationId}:${model.model_identifier}`,
              );
              setMainPreview(model);
            }}
            onSyncCatalog={onSyncCatalog}
          />
          <ModelCatalogPicker
            opened={lightweightPickerOpen}
            title={t("selectWorkspaceLightweightModel")}
            handle={handle}
            integrations={enabledProviderOptions}
            selectedIntegrationId={
              form.values.defaultLightweightModelProviderIntegrationId
            }
            selectedValue={form.values.defaultLightweightModelValue}
            onClose={() => setLightweightPickerOpen(false)}
            onSelectIntegration={(integrationId) => {
              form.setFieldValue(
                "defaultLightweightModelProviderIntegrationId",
                integrationId,
              );
              form.setFieldValue("defaultLightweightModelValue", null);
              setLightweightPreview(null);
            }}
            onSelectModel={(model) => {
              const integrationId =
                form.values.defaultLightweightModelProviderIntegrationId;
              if (integrationId == null) {
                return;
              }
              form.setFieldValue(
                "defaultLightweightModelValue",
                `${integrationId}:${model.model_identifier}`,
              );
              setLightweightPreview(model);
            }}
            onSyncCatalog={onSyncCatalog}
          />
          <Stack gap={4}>
            <Text fw={600}>{t("title")}</Text>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Stack>
          <Text size="sm" c="dimmed">
            {t("currentMain")}
            {formatModelSelectionSummary(settings?.default_model_selection)}
          </Text>
          <Text size="sm" c="dimmed">
            {t("currentLightweight")}
            {formatModelSelectionSummary(
              settings?.effective_default_lightweight_model_selection,
            )}
          </Text>
          <Card withBorder padding="sm">
            <Group justify="space-between" align="center">
              <Stack gap={2}>
                <Text fw={600}>{t("mainModelLabel")}</Text>
                <Text size="sm" c="dimmed">
                  {mainPreview?.model_display_name ??
                    settings?.default_model_selection?.model_display_name ??
                    t("noDefaultModelSelected")}
                </Text>
              </Stack>
              <Button
                variant="light"
                disabled={!canManage}
                onClick={() => setMainPickerOpen(true)}
              >
                {t("changeModel")}
              </Button>
            </Group>
          </Card>
          {form.values.defaultModelValue != null &&
            defaultModelOptions.every(
              (option) => option.value !== form.values.defaultModelValue,
            ) && (
              <Alert
                color="yellow"
                title="Default model is not in the current catalog"
              >
                The saved default snapshot may be stale or the model was removed
                from the latest catalog projection.
              </Alert>
            )}
          <Card withBorder padding="sm">
            <Group justify="space-between" align="center">
              <Stack gap={2}>
                <Text fw={600}>{t("lightweightModelLabel")}</Text>
                <Text size="sm" c="dimmed">
                  {lightweightPreview?.model_display_name ??
                    settings?.default_lightweight_model_selection
                      ?.model_display_name ??
                    t("useMainModel")}
                </Text>
              </Stack>
              <Button
                variant="light"
                disabled={!canManage}
                onClick={() => setLightweightPickerOpen(true)}
              >
                {t("changeModel")}
              </Button>
            </Group>
          </Card>
          {error && <Alert color="red">{error}</Alert>}
          {canManage && (
            <Group justify="flex-end">
              <Button type="submit" loading={submitting}>
                {t("save")}
              </Button>
            </Group>
          )}
        </Stack>
      </form>
    </Card>
  );
}
