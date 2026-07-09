"use client";

/** Workspace default model selection settings card */

import { Alert, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { SelectableModelOptionsEditor } from "@/features/agents/components/SelectableModelOptionsEditor";
import { selectableModelOptionFormValuesFromStoredOptions } from "@/features/agents/model-selection";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
  SelectableModelOptionFormValue,
} from "@/features/agents/model-selection";
import type { WorkspaceModelSettingsResponse } from "@azents/public-client";

interface WorkspaceModelSettingsFormValues {
  defaultSelectableModelOptions: SelectableModelOptionFormValue[];
  defaultMainModelLabel: string | null;
  defaultLightweightModelLabel: string | null;
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
  canManage,
  submitting,
  error,
  onSyncCatalog,
  onSubmit,
}: WorkspaceModelSettingsCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.modelSelection");
  const form = useForm<WorkspaceModelSettingsFormValues>({
    mode: "controlled",
    initialValues: {
      defaultSelectableModelOptions: [],
      defaultMainModelLabel: null,
      defaultLightweightModelLabel: null,
    },
    validate: (values) => {
      const hasEmptyLabel = values.defaultSelectableModelOptions.some(
        (option) => option.label.trim().length === 0,
      );
      const labels = values.defaultSelectableModelOptions.map((option) =>
        option.label.trim(),
      );
      const uniqueLabels = new Set(labels);
      const hasMissingModel = values.defaultSelectableModelOptions.some(
        (option) => option.model_selection_value == null,
      );
      if (
        values.defaultSelectableModelOptions.length === 0 ||
        hasEmptyLabel ||
        uniqueLabels.size !== labels.length ||
        hasMissingModel
      ) {
        return { defaultSelectableModelOptions: t("invalidOptions") };
      }
      return {};
    },
  });

  useEffect(() => {
    form.setValues({
      defaultSelectableModelOptions:
        selectableModelOptionFormValuesFromStoredOptions(
          settings?.default_selectable_model_options ?? [],
        ),
      defaultMainModelLabel: settings?.default_main_model_label ?? null,
      defaultLightweightModelLabel:
        settings?.default_lightweight_model_label ?? null,
    });
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Resynchronize form when server settings change.
  }, [settings]);

  const submit = form.onSubmit((values) => {
    onSubmit(values);
  });

  return (
    <Card withBorder padding="md">
      <form onSubmit={submit}>
        <Stack gap="md">
          <Stack gap="xs">
            <Text fw={600}>{t("title")}</Text>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Stack>
          <SelectableModelOptionsEditor
            handle={handle}
            title={t("optionsTitle")}
            description={t("optionsDescription")}
            options={form.values.defaultSelectableModelOptions}
            mainModelLabel={form.values.defaultMainModelLabel}
            lightweightModelLabel={form.values.defaultLightweightModelLabel}
            providerOptions={providerOptions}
            canEdit={canManage}
            onSyncCatalog={onSyncCatalog}
            onChangeOptions={(options) =>
              form.setFieldValue("defaultSelectableModelOptions", options)
            }
            onChangeMainModelLabel={(label) =>
              form.setFieldValue("defaultMainModelLabel", label)
            }
            onChangeLightweightModelLabel={(label) =>
              form.setFieldValue("defaultLightweightModelLabel", label)
            }
          />
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
