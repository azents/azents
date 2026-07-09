"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ActionIcon,
  Alert,
  Button,
  Group,
  rem,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconGripVertical, IconTrash } from "@tabler/icons-react";
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
import type { DragEndEvent } from "@dnd-kit/core";

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

interface SelectableModelRowProps {
  option: SelectableModelOptionFormValue;
  duplicate: boolean;
  canEdit: boolean;
  canRemove: boolean;
  onChangeLabel: (value: string) => void;
  onChangeModel: () => void;
  onRemove: () => void;
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

function SelectableModelRow({
  option,
  duplicate,
  canEdit,
  canRemove,
  onChangeLabel,
  onChangeModel,
  onRemove,
}: SelectableModelRowProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const {
    attributes,
    isDragging,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
  } = useSortable({ disabled: !canEdit, id: option.id });

  return (
    <Table.Tr
      ref={setNodeRef}
      style={{
        opacity: isDragging ? 0.6 : 1,
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <Table.Td w="0">
        <Tooltip label={t("dragHandleLabel")}>
          <ActionIcon
            ref={setActivatorNodeRef}
            aria-label={t("dragHandleLabel")}
            color="gray"
            disabled={!canEdit}
            variant="subtle"
            {...attributes}
            {...listeners}
          >
            <IconGripVertical size="1rem" />
          </ActionIcon>
        </Tooltip>
      </Table.Td>
      <Table.Td>
        <TextInput
          aria-label={t("optionLabel")}
          value={option.label}
          disabled={!canEdit}
          error={
            option.label.trim() === ""
              ? t("emptyLabel")
              : duplicate
                ? t("duplicateLabel")
                : null
          }
          onChange={(event) => onChangeLabel(event.currentTarget.value)}
        />
      </Table.Td>
      <Table.Td>
        <Stack gap={0}>
          <Text fw={600} size="sm">
            {option.model_display_name ?? t("noModelSelected")}
          </Text>
          <Text size="sm" c="dimmed">
            {option.model_identifier ?? t("chooseModel")}
          </Text>
        </Stack>
      </Table.Td>
      <Table.Td>
        <Group justify="flex-end" gap="xs" wrap="nowrap">
          <Button variant="light" disabled={!canEdit} onClick={onChangeModel}>
            {t("changeModel")}
          </Button>
          <Tooltip label={t("remove")}>
            <ActionIcon
              aria-label={t("remove")}
              color="red"
              disabled={!canEdit || !canRemove}
              variant="subtle"
              onClick={onRemove}
            >
              <IconTrash size="1rem" />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Table.Td>
    </Table.Tr>
  );
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
  const sensors = useSensors(
    useSensor(MouseSensor),
    useSensor(TouchSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const enabledProviderOptions = useMemo(
    () => providerOptions.filter((option) => !option.disabled),
    [providerOptions],
  );
  const labelOptions = useMemo(
    () => selectableModelLabelSelectData(options),
    [options],
  );
  const optionIds = useMemo(
    () => options.map((option) => option.id),
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

  const handleDragEnd = (event: DragEndEvent): void => {
    const { active, over } = event;
    if (over == null || active.id === over.id) {
      return;
    }
    const activeId = String(active.id);
    const overId = String(over.id);
    const activeIndex = options.findIndex((option) => option.id === activeId);
    const overIndex = options.findIndex((option) => option.id === overId);
    if (activeIndex === -1 || overIndex === -1) {
      return;
    }
    handleChangeOptions(arrayMove(options, activeIndex, overIndex));
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

      {options.length > 0 && (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={optionIds}
            strategy={verticalListSortingStrategy}
          >
            <Table.ScrollContainer minWidth={rem(672)}>
              <Table verticalSpacing="sm" withTableBorder>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w="0" />
                    <Table.Th>{t("modelLabelColumn")}</Table.Th>
                    <Table.Th>{t("selectedModelColumn")}</Table.Th>
                    <Table.Th ta="right">{t("actionsColumn")}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {options.map((option, index) => (
                    <SelectableModelRow
                      key={option.id}
                      option={option}
                      duplicate={rowHasDuplicateLabel(options, index)}
                      canEdit={canEdit}
                      canRemove={options.length > 1}
                      onChangeLabel={(value) => {
                        handleChangeOptions(
                          updateOption(options, option.id, (current) => ({
                            ...current,
                            label: value,
                          })),
                        );
                      }}
                      onChangeModel={() => setPickerOptionId(option.id)}
                      onRemove={() => {
                        handleChangeOptions(
                          options.filter((item) => item.id !== option.id),
                        );
                      }}
                    />
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </SortableContext>
        </DndContext>
      )}
    </Stack>
  );
}
