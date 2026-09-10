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
  Badge,
  Box,
  Button,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconGripVertical, IconSettings, IconTrash } from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { ModelCatalogPickerContainer } from "../containers/ModelCatalogPickerContainer";
import {
  createSelectableModelOptionFormValue,
  fallbackSelectableModelLabel,
  hasInvalidImageGenerationSelections,
  imageGenerationModelAvailability,
  imageGenerationModelIdentifier,
  imageGenerationModelSelectionVisible,
  MAX_SELECTABLE_MODEL_OPTIONS,
  MAX_SUBAGENT_GUIDANCE_LENGTH,
  resolveModelContextRange,
  selectableModelLabelSelectData,
  withImageGenerationModelIdentifier,
} from "../model-selection";
import classes from "./SelectableModelOptionsEditor.module.css";
import type {
  ImageGenerationCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidate,
  SelectableModelOptionFormValue,
} from "../model-selection";
import type { DragEndEvent } from "@dnd-kit/core";
import type { ReactNode } from "react";

export interface SelectableModelOptionsEditorProps {
  handle: string;
  title: string;
  description: string;
  options: SelectableModelOptionFormValue[];
  mainModelLabel: string | null;
  lightweightModelLabel: string | null;
  defaultReasoningEffortControl?: ReactNode;
  providerOptions: ProviderIntegrationOption[];
  canEdit: boolean;
  showValidationErrors?: boolean;
  onSyncCatalog: (integrationId: string) => Promise<void>;
  imageGenerationCatalogStates: ReadonlyMap<
    string,
    ImageGenerationCatalogState
  >;
  canSyncImageCatalog: boolean;
  onSyncImageCatalog: (integrationId: string) => Promise<void>;
  onChangeOptions: (options: SelectableModelOptionFormValue[]) => void;
  onChangeMainModelLabel: (label: string | null) => void;
  onChangeLightweightModelLabel: (label: string | null) => void;
}

interface SelectableModelRowProps {
  option: SelectableModelOptionFormValue;
  duplicate: boolean;
  canEdit: boolean;
  canRemove: boolean;
  showValidationErrors: boolean;
  labelInputRef: (node: HTMLInputElement | null) => void;
  onChangeLabel: (value: string) => void;
  onChangeModel: () => void;
  onOpenSettings: () => void;
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
  showValidationErrors,
  labelInputRef,
  onChangeLabel,
  onChangeModel,
  onOpenSettings,
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
    <Box
      ref={setNodeRef}
      className={classes.row}
      style={{
        opacity: isDragging ? 0.6 : 1,
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <Box className={classes.dragHandle}>
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
      </Box>
      <Box className={classes.label}>
        <TextInput
          ref={labelInputRef}
          aria-label={t("optionLabel")}
          value={option.label}
          disabled={!canEdit}
          error={
            showValidationErrors
              ? option.label.trim() === ""
                ? t("emptyLabel")
                : duplicate
                  ? t("duplicateLabel")
                  : null
              : null
          }
          onChange={(event) => onChangeLabel(event.currentTarget.value)}
        />
      </Box>
      <Stack className={classes.model} gap={0}>
        <Text className={classes.modelText} fw={600} size="sm">
          {option.model_display_name ?? t("noModelSelected")}
        </Text>
        <Text className={classes.modelText} size="sm" c="dimmed">
          {option.model_identifier ?? t("chooseModel")}
        </Text>
      </Stack>
      <Box className={classes.actions}>
        <Button
          className={classes.changeModel}
          variant="light"
          disabled={!canEdit}
          onClick={onChangeModel}
        >
          {t("changeModel")}
        </Button>
        <Tooltip label={t("settingsAction")}>
          <ActionIcon
            aria-label={t("settingsAction")}
            color="gray"
            disabled={!canEdit || option.model_selection_value == null}
            variant="subtle"
            onClick={onOpenSettings}
          >
            <IconSettings size="1rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("remove")}>
          <ActionIcon
            className={classes.remove}
            aria-label={t("remove")}
            color="red"
            disabled={!canEdit || !canRemove}
            variant="subtle"
            onClick={onRemove}
          >
            <IconTrash size="1rem" />
          </ActionIcon>
        </Tooltip>
      </Box>
    </Box>
  );
}

interface SelectableModelSettingsModalProps {
  opened: boolean;
  option: SelectableModelOptionFormValue;
  imageGenerationCatalogStates: ReadonlyMap<
    string,
    ImageGenerationCatalogState
  >;
  canSyncImageCatalog: boolean;
  onClose: () => void;
  onChange: (option: SelectableModelOptionFormValue) => void;
  onSyncImageCatalog: (integrationId: string) => Promise<void>;
}

const IMAGE_GENERATION_DEFAULT_VALUE = "__azents_default_image_model__";

function SelectableModelSettingsModal({
  opened,
  option,
  imageGenerationCatalogStates,
  canSyncImageCatalog,
  onClose,
  onChange,
  onSyncImageCatalog,
}: SelectableModelSettingsModalProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const format = useFormatter();
  const context = resolveModelContextRange(
    option.normalized_capabilities?.context_window,
  );
  const outputLimit =
    option.normalized_capabilities?.context_window?.max_output_tokens ?? null;
  const supportedTools =
    option.normalized_capabilities?.built_in_tools?.supported ?? [];
  const imageGenerationEnabled =
    option.builtin_tools.includes("image_generation");
  const integrationId = option.model_provider_integration_id;
  const imageCatalogState =
    integrationId == null
      ? null
      : (imageGenerationCatalogStates.get(integrationId) ?? null);
  const imageModelSelectionVisible =
    imageGenerationEnabled &&
    imageGenerationModelSelectionVisible(imageCatalogState);
  const selectedImageModelIdentifier = imageGenerationModelIdentifier(option);
  const selectedImageModelValue =
    selectedImageModelIdentifier ?? IMAGE_GENERATION_DEFAULT_VALUE;
  const loadedCatalog =
    imageCatalogState?.type === "LOADED" ? imageCatalogState.data : null;
  const selectableImageEntries =
    loadedCatalog?.generation_current === true ? loadedCatalog.entries : [];
  const selectedImageModelAvailability =
    selectedImageModelIdentifier == null
      ? "AVAILABLE"
      : imageGenerationModelAvailability(
          selectedImageModelIdentifier,
          imageCatalogState,
        );
  const savedImageModelNeedsRecovery =
    selectedImageModelIdentifier != null &&
    selectedImageModelAvailability !== "AVAILABLE";
  const selectedImageEntry = selectableImageEntries.find(
    (entry) => entry.provider_model_identifier === selectedImageModelIdentifier,
  );
  const imageModelData = [
    {
      value: IMAGE_GENERATION_DEFAULT_VALUE,
      label: t("imageModelDefault"),
    },
    ...selectableImageEntries.map((entry) => ({
      value: entry.provider_model_identifier,
      label: entry.display_name,
    })),
    ...(savedImageModelNeedsRecovery
      ? [
          {
            value: selectedImageModelIdentifier,
            label: t("imageModelSavedUnavailable", {
              model: selectedImageModelIdentifier,
            }),
            disabled: true,
          },
        ]
      : []),
  ];
  const imageModelError =
    selectedImageModelAvailability === "UNAVAILABLE"
      ? t("imageModelUnavailableError")
      : selectedImageModelAvailability === "UNVERIFIED"
        ? t("imageModelUnverifiedError")
        : loadedCatalog?.default_available === false
          ? t("imageDefaultUnavailableError")
          : null;
  const imageModelDescription =
    selectedImageModelIdentifier == null
      ? t("imageModelDefaultDescription")
      : (selectedImageEntry?.description ?? t("imageModelPinnedDescription"));
  const savedImageModelNotice =
    selectedImageModelAvailability === "UNAVAILABLE" ? (
      <Alert color="orange" title={t("imageModelUnavailableTitle")}>
        {t("imageModelUnavailableDescription")}
      </Alert>
    ) : selectedImageModelAvailability === "UNVERIFIED" ? (
      <Alert color="orange" title={t("imageModelUnverifiedTitle")}>
        {t("imageModelUnverifiedDescription")}
      </Alert>
    ) : null;
  const syncImageCatalogButton =
    integrationId != null && canSyncImageCatalog ? (
      <Button
        size="xs"
        variant="light"
        onClick={() => {
          void onSyncImageCatalog(integrationId);
        }}
      >
        {t("imageCatalogSync")}
      </Button>
    ) : null;
  let imageCatalogNotice: ReactNode = null;
  if (imageCatalogState == null) {
    imageCatalogNotice = (
      <Alert color="yellow" title={t("imageCatalogUnavailableTitle")}>
        {t("imageCatalogUnavailableDescription")}
      </Alert>
    );
  } else {
    switch (imageCatalogState.type) {
      case "LOADING":
        imageCatalogNotice = (
          <Alert color="blue" title={t("imageCatalogLoadingTitle")}>
            {t("imageCatalogLoadingDescription")}
          </Alert>
        );
        break;
      case "ERROR":
        imageCatalogNotice = (
          <Alert color="orange" title={t("imageCatalogErrorTitle")}>
            <Stack gap="xs">
              <Text size="sm">{t("imageCatalogErrorDescription")}</Text>
              {syncImageCatalogButton}
            </Stack>
          </Alert>
        );
        break;
      case "UNSUPPORTED":
        break;
      case "LOADED": {
        const catalog = imageCatalogState.data;
        if (!catalog.default_available) {
          imageCatalogNotice = (
            <Alert color="red" title={t("imageDefaultUnavailableTitle")}>
              {t("imageDefaultUnavailableDescription")}
            </Alert>
          );
        } else if (!catalog.generation_current) {
          imageCatalogNotice = (
            <Alert color="orange" title={t("imageCatalogChangedTitle")}>
              <Stack gap="xs">
                <Text size="sm">{t("imageCatalogChangedDescription")}</Text>
                {syncImageCatalogButton}
              </Stack>
            </Alert>
          );
        } else if (catalog.snapshot_id == null) {
          imageCatalogNotice = (
            <Alert color="blue" title={t("imageCatalogNeverSyncedTitle")}>
              <Stack gap="xs">
                <Text size="sm">{t("imageCatalogNeverSyncedDescription")}</Text>
                {syncImageCatalogButton}
              </Stack>
            </Alert>
          );
        } else if (catalog.latest_attempt?.status === "failed") {
          imageCatalogNotice = (
            <Alert color="yellow" title={t("imageCatalogLastSyncFailedTitle")}>
              <Stack gap="xs">
                <Text size="sm">
                  {t("imageCatalogLastSyncFailedDescription")}
                </Text>
                {syncImageCatalogButton}
              </Stack>
            </Alert>
          );
        } else if (catalog.stale) {
          imageCatalogNotice = (
            <Alert color="yellow" title={t("imageCatalogStaleTitle")}>
              <Stack gap="xs">
                <Text size="sm">{t("imageCatalogStaleDescription")}</Text>
                {syncImageCatalogButton}
              </Stack>
            </Alert>
          );
        } else if (catalog.entries.length === 0) {
          imageCatalogNotice = (
            <Alert color="blue" title={t("imageCatalogEmptyTitle")}>
              <Stack gap="xs">
                <Text size="sm">{t("imageCatalogEmptyDescription")}</Text>
                {syncImageCatalogButton}
              </Stack>
            </Alert>
          );
        }
        break;
      }
    }
  }
  const formatToolLabel = (tool: string): string => {
    switch (tool) {
      case "web_search":
        return t("builtinToolWebSearch");
      case "image_generation":
        return t("builtinToolImageGeneration");
      default:
        return tool;
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("settingsTitle", {
        label: option.label || t("newOption"),
      })}
      centered
    >
      <Stack gap="md">
        <NumberInput
          label={t("contextWindowTokensLabel")}
          description={
            context.defaultInputTokens == null
              ? t("capabilityLimitUnknown")
              : context.maxInputTokens == null
                ? t("contextCapabilityDefaultOnly", {
                    tokens: format.number(context.defaultInputTokens),
                  })
                : context.defaultInputTokens === context.maxInputTokens
                  ? t("contextCapabilitySingle", {
                      tokens: format.number(context.defaultInputTokens),
                    })
                  : t("contextCapabilityRange", {
                      defaultTokens: format.number(context.defaultInputTokens),
                      maxTokens: format.number(context.maxInputTokens),
                    })
          }
          placeholder={t("useModelDefault")}
          min={1}
          step={1}
          allowDecimal={false}
          allowNegative={false}
          value={option.context_window_tokens ?? ""}
          onChange={(value) =>
            onChange({
              ...option,
              context_window_tokens: typeof value === "number" ? value : null,
            })
          }
        />
        <NumberInput
          label={t("maxOutputTokensLabel")}
          description={
            outputLimit == null
              ? t("capabilityLimitUnknown")
              : t("capabilityLimit", { tokens: format.number(outputLimit) })
          }
          placeholder={t("noTokenCap")}
          min={1}
          step={1}
          allowDecimal={false}
          allowNegative={false}
          value={option.max_output_tokens ?? ""}
          onChange={(value) =>
            onChange({
              ...option,
              max_output_tokens: typeof value === "number" ? value : null,
            })
          }
        />
        <Stack gap="xs">
          <Text fw={500} size="sm">
            {t("builtinToolsLabel")}
          </Text>
          {supportedTools.length === 0 ? (
            <Text c="dimmed" size="sm">
              {t("noBuiltinTools")}
            </Text>
          ) : (
            <Checkbox.Group
              value={option.builtin_tools}
              onChange={(builtinTools) => {
                const builtinToolConfigs = {
                  ...option.builtin_tool_configs,
                };
                for (const toolName of Object.keys(builtinToolConfigs)) {
                  if (!builtinTools.includes(toolName)) {
                    delete builtinToolConfigs[toolName];
                  }
                }
                onChange({
                  ...option,
                  builtin_tools: builtinTools,
                  builtin_tool_configs: builtinToolConfigs,
                });
              }}
            >
              <Stack gap="xs">
                {supportedTools.map((tool) => (
                  <Checkbox
                    key={tool}
                    value={tool}
                    label={formatToolLabel(tool)}
                  />
                ))}
              </Stack>
            </Checkbox.Group>
          )}
          {imageModelSelectionVisible && (
            <Box ml="xl">
              <Stack gap="xs">
                <Select
                  label={t("imageModelLabel")}
                  description={t("imageModelDescription")}
                  data={imageModelData}
                  value={selectedImageModelValue}
                  allowDeselect={false}
                  error={imageModelError}
                  renderOption={({ option: imageModelOption }) => (
                    <Group
                      gap="sm"
                      justify="space-between"
                      wrap="nowrap"
                      w="100%"
                    >
                      <Stack gap={0}>
                        <Text size="sm">{imageModelOption.label}</Text>
                        <Text c="dimmed" size="xs">
                          {imageModelOption.value ===
                          IMAGE_GENERATION_DEFAULT_VALUE
                            ? t("imageModelDefaultDescription")
                            : (selectableImageEntries.find(
                                (entry) =>
                                  entry.provider_model_identifier ===
                                  imageModelOption.value,
                              )?.description ??
                              t("imageModelUnavailableDescription"))}
                        </Text>
                      </Stack>
                      {(imageModelOption.value ===
                        IMAGE_GENERATION_DEFAULT_VALUE ||
                        selectableImageEntries.find(
                          (entry) =>
                            entry.provider_model_identifier ===
                            imageModelOption.value,
                        )?.recommendation_rank === 1) && (
                        <Badge size="xs" variant="light">
                          {t("imageModelRecommended")}
                        </Badge>
                      )}
                    </Group>
                  )}
                  onChange={(imageGenerationModel) => {
                    if (imageGenerationModel == null) {
                      return;
                    }
                    if (
                      imageGenerationModel === IMAGE_GENERATION_DEFAULT_VALUE
                    ) {
                      onChange(
                        withImageGenerationModelIdentifier(option, null),
                      );
                      return;
                    }
                    if (
                      selectableImageEntries.some(
                        (entry) =>
                          entry.provider_model_identifier ===
                          imageGenerationModel,
                      )
                    ) {
                      onChange(
                        withImageGenerationModelIdentifier(
                          option,
                          imageGenerationModel,
                        ),
                      );
                    }
                  }}
                />
                <Text c="dimmed" size="xs">
                  {imageModelDescription}
                </Text>
                {savedImageModelNotice}
                {imageCatalogNotice}
              </Stack>
            </Box>
          )}
        </Stack>
        <Stack gap="xs">
          <Text fw={500} size="sm">
            {t("subagentsSectionLabel")}
          </Text>
          <Switch
            label={t("subagentEnabledLabel")}
            description={t("subagentEnabledDescription")}
            checked={option.subagent_enabled}
            onChange={(event) =>
              onChange({
                ...option,
                subagent_enabled: event.currentTarget.checked,
              })
            }
          />
          <Text c="dimmed" size="sm">
            {t("subagentInheritanceDescription")}
          </Text>
          <Textarea
            label={t("subagentGuidanceLabel")}
            description={t("subagentGuidanceDescription", {
              max: MAX_SUBAGENT_GUIDANCE_LENGTH,
            })}
            placeholder={t("subagentGuidancePlaceholder")}
            value={option.subagent_guidance ?? ""}
            disabled={!option.subagent_enabled}
            maxLength={MAX_SUBAGENT_GUIDANCE_LENGTH}
            autosize
            minRows={3}
            onChange={(event) =>
              onChange({
                ...option,
                subagent_guidance: event.currentTarget.value || null,
              })
            }
          />
        </Stack>
        <Group justify="flex-end">
          <Button variant="light" onClick={onClose}>
            {t("settingsDone")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function SelectableModelOptionsEditor({
  handle,
  title,
  description,
  options,
  mainModelLabel,
  lightweightModelLabel,
  defaultReasoningEffortControl,
  providerOptions,
  canEdit,
  showValidationErrors = false,
  onSyncCatalog,
  imageGenerationCatalogStates,
  canSyncImageCatalog,
  onSyncImageCatalog,
  onChangeOptions,
  onChangeMainModelLabel,
  onChangeLightweightModelLabel,
}: SelectableModelOptionsEditorProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const [pickerOptionId, setPickerOptionId] = useState<string | null>(null);
  const [settingsOptionId, setSettingsOptionId] = useState<string | null>(null);
  const [pendingFocusOptionId, setPendingFocusOptionId] = useState<
    string | null
  >(null);
  const labelInputRefs = useRef(new Map<string, HTMLInputElement>());
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
  const settingsOption =
    options.find((option) => option.id === settingsOptionId) ?? null;
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
  const hasInvalidImageGenerationSelection =
    hasInvalidImageGenerationSelections(options, imageGenerationCatalogStates);

  useEffect(() => {
    if (pendingFocusOptionId == null) {
      return;
    }
    const input = labelInputRefs.current.get(pendingFocusOptionId);
    if (input == null) {
      return;
    }
    input.focus();
    setPendingFocusOptionId(null);
  }, [options, pendingFocusOptionId]);

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
    const id = createOptionId();
    const nextOptions = [...options, createSelectableModelOptionFormValue(id)];
    setPendingFocusOptionId(id);
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
        <Text fw={500}>{title}</Text>
        <Text size="sm" c="dimmed">
          {description}
        </Text>
        {showValidationErrors && options.length === 0 && (
          <Alert color="red">{t("emptyList")}</Alert>
        )}
        {options.length >= MAX_SELECTABLE_MODEL_OPTIONS && (
          <Alert color="blue">{t("maxOptions")}</Alert>
        )}
        {showValidationErrors && hasEmptyLabels && (
          <Alert color="red">{t("emptyLabel")}</Alert>
        )}
        {showValidationErrors && hasDuplicateLabels && (
          <Alert color="red">{t("duplicateLabel")}</Alert>
        )}
        {showValidationErrors && hasMissingModels && (
          <Alert color="red">{t("missingModel")}</Alert>
        )}
        {showValidationErrors && hasInvalidImageGenerationSelection && (
          <Alert color="red">{t("invalidImageModel")}</Alert>
        )}
      </Stack>

      {activeOption != null && (
        <ModelCatalogPickerContainer
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
                context_window_tokens: null,
                max_output_tokens: null,
                builtin_tools: [],
                builtin_tool_configs: {},
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
                context_window_tokens: null,
                max_output_tokens: null,
                builtin_tools: [
                  ...(model.normalized_capabilities.built_in_tools?.supported ??
                    []),
                ],
                builtin_tool_configs: {},
              })),
            );
          }}
          onSyncCatalog={onSyncCatalog}
        />
      )}

      {settingsOption != null && (
        <SelectableModelSettingsModal
          opened={settingsOptionId != null}
          option={settingsOption}
          imageGenerationCatalogStates={imageGenerationCatalogStates}
          canSyncImageCatalog={canSyncImageCatalog}
          onClose={() => setSettingsOptionId(null)}
          onChange={(nextOption) => {
            handleChangeOptions(
              updateOption(options, nextOption.id, () => nextOption),
            );
          }}
          onSyncImageCatalog={onSyncImageCatalog}
        />
      )}

      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Stack gap="sm">
          <Select
            label={t("mainLabel")}
            description={t("mainDescription")}
            data={labelOptions}
            value={mainLabelValue}
            disabled={!canEdit || labelOptions.length === 0}
            onChange={onChangeMainModelLabel}
          />
          {defaultReasoningEffortControl}
        </Stack>
        <Select
          label={t("lightweightLabel")}
          description={t("lightweightDescription")}
          data={labelOptions}
          value={lightweightLabelValue}
          disabled={!canEdit || labelOptions.length === 0}
          onChange={onChangeLightweightModelLabel}
        />
      </SimpleGrid>

      <Group justify="flex-start">
        <Button
          variant="light"
          disabled={!canEdit || options.length >= MAX_SELECTABLE_MODEL_OPTIONS}
          onClick={handleAddOption}
        >
          {t("addOption")}
        </Button>
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
            <Box className={classes.optionsList}>
              <Box className={classes.header}>
                <Box />
                <Text size="sm">{t("modelLabelColumn")}</Text>
                <Text size="sm">{t("selectedModelColumn")}</Text>
                <Text className={classes.actionsHeader} size="sm">
                  {t("actionsColumn")}
                </Text>
              </Box>
              {options.map((option, index) => (
                <SelectableModelRow
                  key={option.id}
                  option={option}
                  duplicate={rowHasDuplicateLabel(options, index)}
                  canEdit={canEdit}
                  canRemove={options.length > 1}
                  showValidationErrors={showValidationErrors}
                  labelInputRef={(node) => {
                    if (node == null) {
                      labelInputRefs.current.delete(option.id);
                    } else {
                      labelInputRefs.current.set(option.id, node);
                    }
                  }}
                  onChangeLabel={(value) => {
                    handleChangeOptions(
                      updateOption(options, option.id, (current) => ({
                        ...current,
                        label: value,
                      })),
                    );
                  }}
                  onChangeModel={() => setPickerOptionId(option.id)}
                  onOpenSettings={() => setSettingsOptionId(option.id)}
                  onRemove={() => {
                    handleChangeOptions(
                      options.filter((item) => item.id !== option.id),
                    );
                  }}
                />
              ))}
            </Box>
          </SortableContext>
        </DndContext>
      )}
    </Stack>
  );
}
