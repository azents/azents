"use client";

import {
  Alert,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import {
  fallbackSelectableModelLabel,
  MAX_SELECTABLE_MODEL_OPTIONS,
  nextSelectableModelOptionLabel,
  selectableModelLabelSelectData,
} from "../model-selection";
import { ModelCatalogPicker } from "./ModelCatalogPicker";
import type {
  ProviderIntegrationOption,
  SelectableModelCandidate,
  SelectableModelOptionFormValue,
} from "../model-selection";

export interface SelectableModelOptionsEditorProps {
  handle: string;
  title: string;
  description: string;
  options: SelectableModelOptionFormValue[];
  mainModelLabel: string | null;
  lightweightModelLabel: string | null;
  providerOptions: ProviderIntegrationOption[];
  canEdit: boolean;
  onSyncCatalog: (integrationId: string) => void;
  onChangeOptions: (options: SelectableModelOptionFormValue[]) => void;
  onChangeMainModelLabel: (label: string | null) => void;
  onChangeLightweightModelLabel: (label: string | null) => void;
}

function createOptionId(): string {
  return `option-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function optionModelValue(
  integrationId: string | null,
  model: SelectableModelCandidate,
): string | null {
  if (integrationId == null) {
    return null;
  }
  return `${integrationId}:${model.model_identifier}`;
}

function rowHasDuplicateLabel(
  options: SelectableModelOptionFormValue[],
  rowIndex: number,
): boolean {
  const label = options[rowIndex]?.label.trim() ?? "";
  if (label.length === 0) {
    return false;
  }
  return options.some(
    (option, index) => index !== rowIndex && option.label.trim() === label,
  );
}

function updateOption(
  options: SelectableModelOptionFormValue[],
  id: string,
  update: (
    option: SelectableModelOptionFormValue,
  ) => SelectableModelOptionFormValue,
): SelectableModelOptionFormValue[] {
  return options.map((option) => (option.id === id ? update(option) : option));
}

function moveOption(
  options: SelectableModelOptionFormValue[],
  fromIndex: number,
  toIndex: number,
): SelectableModelOptionFormValue[] {
  const option = options[fromIndex];
  if (option == null || toIndex < 0 || toIndex >= options.length) {
    return options;
  }
  const withoutOption = options.filter((_, index) => index !== fromIndex);
  return [
    ...withoutOption.slice(0, toIndex),
    option,
    ...withoutOption.slice(toIndex),
  ];
}

export function SelectableModelOptionsEditor({
  handle,
  title,
  description,
  options,
  mainModelLabel,
  lightweightModelLabel,
  providerOptions,
  canEdit,
  onSyncCatalog,
  onChangeOptions,
  onChangeMainModelLabel,
  onChangeLightweightModelLabel,
}: SelectableModelOptionsEditorProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const [pickerOptionId, setPickerOptionId] = useState<string | null>(null);

  const enabledProviderOptions = useMemo(
    () => providerOptions.filter((option) => !option.disabled),
    [providerOptions],
  );
  const labelOptions = useMemo(
    () => selectableModelLabelSelectData(options),
    [options],
  );
  const activeOption =
    options.find((option) => option.id === pickerOptionId) ?? null;
  const mainLabelValue = fallbackSelectableModelLabel(mainModelLabel, options);
  const lightweightLabelValue = fallbackSelectableModelLabel(
    lightweightModelLabel,
    options,
  );
  const hasEmptyLabels = options.some((option) => option.label.trim() === "");
  const hasMissingModels = options.some(
    (option) => option.model_selection_value == null,
  );
  const hasDuplicateLabels = options.some((_, index) =>
    rowHasDuplicateLabel(options, index),
  );

  const handleChangeOptions = (
    nextOptions: SelectableModelOptionFormValue[],
  ): void => {
    onChangeOptions(nextOptions);
    onChangeMainModelLabel(
      fallbackSelectableModelLabel(mainModelLabel, nextOptions),
    );
    onChangeLightweightModelLabel(
      fallbackSelectableModelLabel(lightweightModelLabel, nextOptions),
    );
  };

  const handleAddOption = (): void => {
    if (options.length >= MAX_SELECTABLE_MODEL_OPTIONS) {
      return;
    }
    const nextOptions = [
      ...options,
      {
        id: createOptionId(),
        label: nextSelectableModelOptionLabel(options),
        model_provider_integration_id: null,
        model_selection_value: null,
        model_display_name: null,
        model_identifier: null,
        normalized_capabilities: null,
      },
    ];
    handleChangeOptions(nextOptions);
  };

  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap="xs">
            <Text fw={500}>{title}</Text>
            <Text size="sm" c="dimmed">
              {description}
            </Text>
          </Stack>
          <Button
            variant="light"
            disabled={
              !canEdit || options.length >= MAX_SELECTABLE_MODEL_OPTIONS
            }
            onClick={handleAddOption}
          >
            {t("addOption")}
          </Button>
        </Group>
        {options.length === 0 && <Alert color="red">{t("emptyList")}</Alert>}
        {options.length >= MAX_SELECTABLE_MODEL_OPTIONS && (
          <Alert color="blue">{t("maxOptions")}</Alert>
        )}
        {hasEmptyLabels && <Alert color="red">{t("emptyLabel")}</Alert>}
        {hasDuplicateLabels && <Alert color="red">{t("duplicateLabel")}</Alert>}
        {hasMissingModels && <Alert color="red">{t("missingModel")}</Alert>}
      </Stack>

      {activeOption != null && (
        <ModelCatalogPicker
          opened={pickerOptionId != null}
          title={t("selectModelTitle", {
            label: activeOption.label || t("newOption"),
          })}
          handle={handle}
          integrations={enabledProviderOptions}
          selectedIntegrationId={activeOption.model_provider_integration_id}
          selectedValue={activeOption.model_selection_value}
          onClose={() => setPickerOptionId(null)}
          onSelectIntegration={(integrationId) => {
            handleChangeOptions(
              updateOption(options, activeOption.id, (option) => ({
                ...option,
                model_provider_integration_id: integrationId,
                model_selection_value: null,
                model_display_name: null,
                model_identifier: null,
                normalized_capabilities: null,
              })),
            );
          }}
          onSelectModel={(model) => {
            handleChangeOptions(
              updateOption(options, activeOption.id, (option) => ({
                ...option,
                model_selection_value: optionModelValue(
                  option.model_provider_integration_id,
                  model,
                ),
                model_display_name: model.model_display_name,
                model_identifier: model.model_identifier,
                normalized_capabilities: model.normalized_capabilities,
              })),
            );
          }}
          onSyncCatalog={onSyncCatalog}
        />
      )}

      <Group align="flex-start" grow>
        <Select
          label={t("mainLabel")}
          description={t("mainDescription")}
          data={labelOptions}
          value={mainLabelValue}
          disabled={!canEdit || labelOptions.length === 0}
          onChange={onChangeMainModelLabel}
        />
        <Select
          label={t("lightweightLabel")}
          description={t("lightweightDescription")}
          data={labelOptions}
          value={lightweightLabelValue}
          disabled={!canEdit || labelOptions.length === 0}
          onChange={onChangeLightweightModelLabel}
        />
      </Group>

      <Stack gap="sm">
        {options.map((option, index) => {
          const duplicate = rowHasDuplicateLabel(options, index);
          return (
            <Card key={option.id} withBorder padding="sm">
              <Stack gap="sm">
                <Group align="flex-end" grow>
                  <TextInput
                    label={t("optionLabel")}
                    value={option.label}
                    disabled={!canEdit}
                    error={
                      option.label.trim() === ""
                        ? t("emptyLabel")
                        : duplicate
                          ? t("duplicateLabel")
                          : null
                    }
                    onChange={(event) => {
                      handleChangeOptions(
                        updateOption(options, option.id, (current) => ({
                          ...current,
                          label: event.currentTarget.value,
                        })),
                      );
                    }}
                  />
                  <Group justify="flex-end" gap="xs">
                    <Button
                      variant="subtle"
                      disabled={!canEdit || index === 0}
                      onClick={() =>
                        handleChangeOptions(
                          moveOption(options, index, index - 1),
                        )
                      }
                    >
                      {t("moveUp")}
                    </Button>
                    <Button
                      variant="subtle"
                      disabled={!canEdit || index === options.length - 1}
                      onClick={() =>
                        handleChangeOptions(
                          moveOption(options, index, index + 1),
                        )
                      }
                    >
                      {t("moveDown")}
                    </Button>
                    <Button
                      color="red"
                      variant="subtle"
                      disabled={!canEdit || options.length <= 1}
                      onClick={() => {
                        handleChangeOptions(
                          options.filter((item) => item.id !== option.id),
                        );
                      }}
                    >
                      {t("remove")}
                    </Button>
                  </Group>
                </Group>
                <Group justify="space-between" align="center">
                  <Stack gap="xs">
                    <Text fw={600}>
                      {option.model_display_name ?? t("noModelSelected")}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {option.model_identifier ?? t("chooseModel")}
                    </Text>
                  </Stack>
                  <Button
                    variant="light"
                    disabled={!canEdit}
                    onClick={() => setPickerOptionId(option.id)}
                  >
                    {t("changeModel")}
                  </Button>
                </Group>
              </Stack>
            </Card>
          );
        })}
      </Stack>
    </Stack>
  );
}
