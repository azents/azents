"use client";

import { closestCenter, DndContext } from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
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
  Divider,
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
import {
  IconArrowDown,
  IconArrowUp,
  IconCopy,
  IconGripVertical,
  IconPlus,
  IconSettings,
  IconTrash,
} from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import { configurableBuiltinTools } from "@/shared/lib/model-capability-support";
import {
  candidateHasDuplicateModel,
  rowHasDuplicateLabel,
  updateCandidate,
  updateOption,
} from "../model-option-editor";
import {
  imageGenerationModelAvailability,
  imageGenerationModelIdentifier,
  imageGenerationModelSelectionVisible,
  MAX_SELECTABLE_MODEL_CANDIDATES,
  MAX_SELECTABLE_MODEL_OPTIONS,
  MAX_SUBAGENT_GUIDANCE_LENGTH,
  resolveModelContextRange,
  withImageGenerationModelIdentifier,
} from "../model-selection";
import classes from "./SelectableModelOptionsEditor.module.css";
import type { SelectableModelOptionsEditorController } from "../containers/useSelectableModelOptionsEditor";
import type {
  ImageGenerationCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidateFormValue,
  SelectableModelOptionFormValue,
} from "../model-selection";
import type { useSortable } from "@dnd-kit/sortable";
import type { ComponentType, ReactNode } from "react";

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

export interface SelectableModelOptionsEditorViewProps extends SelectableModelOptionsEditorProps {
  controller: SelectableModelOptionsEditorController;
  modelPicker: ReactNode;
  OptionCardComponent: ComponentType<OptionCardProps>;
}

interface CandidateRowProps {
  candidate: SelectableModelCandidateFormValue;
  index: number;
  duplicate: boolean;
  canEdit: boolean;
  canRemove: boolean;
  canMoveDown: boolean;
  showValidationErrors: boolean;
  onChangeModel: () => void;
  onOpenSettings: () => void;
  onCopyPrimarySettings: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
}

function CandidateRow({
  candidate,
  index,
  duplicate,
  canEdit,
  canRemove,
  canMoveDown,
  showValidationErrors,
  onChangeModel,
  onOpenSettings,
  onCopyPrimarySettings,
  onMoveUp,
  onMoveDown,
  onRemove,
}: CandidateRowProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const missing = candidate.model_selection_value == null;
  return (
    <Box className={classes.candidateRow}>
      <Group gap="xs" wrap="nowrap" className={classes.candidateIdentity}>
        <Badge size="sm" variant={index === 0 ? "filled" : "light"}>
          {index === 0
            ? t("primary")
            : t("fallbackOrdinal", { ordinal: index })}
        </Badge>
        <Stack gap={0} className={classes.model}>
          <Text className={classes.modelText} fw={600} size="sm">
            {candidate.model_display_name ?? t("noModelSelected")}
          </Text>
          <Text className={classes.modelText} size="xs" c="dimmed">
            {candidate.model_identifier ?? t("chooseModel")}
          </Text>
          {showValidationErrors && missing ? (
            <Text size="xs" c="red">
              {t("missingCandidateModel")}
            </Text>
          ) : null}
          {showValidationErrors && duplicate ? (
            <Text size="xs" c="red">
              {t("duplicateCandidate")}
            </Text>
          ) : null}
        </Stack>
      </Group>
      <Box className={classes.candidateActions}>
        <Button
          variant="light"
          size="compact-sm"
          disabled={!canEdit}
          onClick={onChangeModel}
        >
          {candidate.model_selection_value == null
            ? t("chooseCandidate")
            : t("changeModel")}
        </Button>
        {index > 0 ? (
          <Tooltip label={t("copyPrimarySettings")}>
            <ActionIcon
              aria-label={t("copyPrimarySettings")}
              color="gray"
              disabled={!canEdit || candidate.model_selection_value == null}
              variant="subtle"
              onClick={onCopyPrimarySettings}
            >
              <IconCopy size="1rem" />
            </ActionIcon>
          </Tooltip>
        ) : null}
        <Tooltip label={t("settingsAction")}>
          <ActionIcon
            aria-label={t("settingsAction")}
            color="gray"
            disabled={!canEdit || candidate.model_selection_value == null}
            variant="subtle"
            onClick={onOpenSettings}
          >
            <IconSettings size="1rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("moveCandidateUp")}>
          <ActionIcon
            aria-label={t("moveCandidateUp")}
            color="gray"
            disabled={!canEdit || index === 0}
            variant="subtle"
            onClick={onMoveUp}
          >
            <IconArrowUp size="1rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("moveCandidateDown")}>
          <ActionIcon
            aria-label={t("moveCandidateDown")}
            color="gray"
            disabled={!canEdit || !canMoveDown}
            variant="subtle"
            onClick={onMoveDown}
          >
            <IconArrowDown size="1rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("removeCandidate")}>
          <ActionIcon
            aria-label={t("removeCandidate")}
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

export interface OptionCardProps {
  option: SelectableModelOptionFormValue;
  duplicateLabel: boolean;
  canEdit: boolean;
  canRemove: boolean;
  showValidationErrors: boolean;
  labelInputRef: (node: HTMLInputElement | null) => void;
  onChangeLabel: (value: string) => void;
  onOpenLabelSettings: () => void;
  onAddCandidate: () => void;
  onChangeCandidateModel: (candidateId: string) => void;
  onOpenCandidateSettings: (candidateId: string) => void;
  onCopyPrimarySettings: (candidateId: string) => void;
  onMoveCandidate: (candidateId: string, direction: -1 | 1) => void;
  onRemoveCandidate: (candidateId: string) => void;
  onRemoveOption: () => void;
}

export function OptionCard({
  option,
  duplicateLabel,
  canEdit,
  canRemove,
  showValidationErrors,
  labelInputRef,
  onChangeLabel,
  onOpenLabelSettings,
  onAddCandidate,
  onChangeCandidateModel,
  onOpenCandidateSettings,
  onCopyPrimarySettings,
  onMoveCandidate,
  onRemoveCandidate,
  onRemoveOption,
  sortable,
}: OptionCardProps & {
  sortable: Pick<
    ReturnType<typeof useSortable>,
    | "attributes"
    | "isDragging"
    | "listeners"
    | "setActivatorNodeRef"
    | "setNodeRef"
    | "transform"
    | "transition"
  >;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const {
    attributes,
    isDragging,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
  } = sortable;
  return (
    <Box
      ref={setNodeRef}
      className={classes.optionCard}
      style={{
        opacity: isDragging ? 0.6 : 1,
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <Box className={classes.optionHeader}>
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
        <TextInput
          ref={labelInputRef}
          className={classes.labelInput}
          aria-label={t("optionLabel")}
          value={option.label}
          disabled={!canEdit}
          error={
            showValidationErrors
              ? option.label.trim() === ""
                ? t("emptyLabel")
                : duplicateLabel
                  ? t("duplicateLabel")
                  : null
              : null
          }
          onChange={(event) => onChangeLabel(event.currentTarget.value)}
        />
        <Tooltip label={t("labelSettingsAction")}>
          <ActionIcon
            aria-label={t("labelSettingsAction")}
            color="gray"
            disabled={!canEdit}
            variant="subtle"
            onClick={onOpenLabelSettings}
          >
            <IconSettings size="1rem" />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("removeLabel")}>
          <ActionIcon
            aria-label={t("removeLabel")}
            color="red"
            disabled={!canEdit || !canRemove}
            variant="subtle"
            onClick={onRemoveOption}
          >
            <IconTrash size="1rem" />
          </ActionIcon>
        </Tooltip>
      </Box>
      <Stack gap="xs" className={classes.candidateList}>
        {option.candidates.map((candidate, index) => (
          <CandidateRow
            key={candidate.id}
            candidate={candidate}
            index={index}
            duplicate={candidateHasDuplicateModel(option, index)}
            canEdit={canEdit}
            canRemove={option.candidates.length > 1}
            canMoveDown={index < option.candidates.length - 1}
            showValidationErrors={showValidationErrors}
            onChangeModel={() => onChangeCandidateModel(candidate.id)}
            onOpenSettings={() => onOpenCandidateSettings(candidate.id)}
            onCopyPrimarySettings={() => onCopyPrimarySettings(candidate.id)}
            onMoveUp={() => onMoveCandidate(candidate.id, -1)}
            onMoveDown={() => onMoveCandidate(candidate.id, 1)}
            onRemove={() => onRemoveCandidate(candidate.id)}
          />
        ))}
      </Stack>
      <Group justify="flex-start">
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<IconPlus size="1rem" />}
          disabled={
            !canEdit ||
            option.candidates.length >= MAX_SELECTABLE_MODEL_CANDIDATES
          }
          onClick={onAddCandidate}
        >
          {t("addFallbackCandidate")}
        </Button>
        <Text size="xs" c="dimmed">
          {t("candidateCount", {
            count: option.candidates.length,
            max: MAX_SELECTABLE_MODEL_CANDIDATES,
          })}
        </Text>
      </Group>
    </Box>
  );
}

interface SelectableModelSettingsModalProps {
  opened: boolean;
  label: string;
  candidate: SelectableModelCandidateFormValue;
  imageGenerationCatalogStates: ReadonlyMap<
    string,
    ImageGenerationCatalogState
  >;
  canSyncImageCatalog: boolean;
  onClose: () => void;
  onChange: (candidate: SelectableModelCandidateFormValue) => void;
  onSyncImageCatalog: (integrationId: string) => Promise<void>;
}

const IMAGE_GENERATION_DEFAULT_VALUE = "__azents_default_image_model__";

function SelectableModelSettingsModal({
  opened,
  label,
  candidate,
  imageGenerationCatalogStates,
  canSyncImageCatalog,
  onClose,
  onChange,
  onSyncImageCatalog,
}: SelectableModelSettingsModalProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const format = useFormatter();
  const context = resolveModelContextRange(
    candidate.normalized_capabilities?.context_window,
  );
  const outputLimit =
    candidate.normalized_capabilities?.context_window?.max_output_tokens ??
    null;
  const supportedTools = configurableBuiltinTools(
    candidate.normalized_capabilities,
  );
  const imageGenerationEnabled =
    candidate.builtin_tools.includes("image_generation");
  const integrationId = candidate.model_provider_integration_id;
  const imageCatalogState =
    integrationId == null
      ? null
      : (imageGenerationCatalogStates.get(integrationId) ?? null);
  const imageModelSelectionVisible =
    imageGenerationEnabled &&
    imageGenerationModelSelectionVisible(imageCatalogState);
  const selectedImageModelIdentifier =
    imageGenerationModelIdentifier(candidate);
  const selectedImageModelValue =
    selectedImageModelIdentifier ?? IMAGE_GENERATION_DEFAULT_VALUE;
  const loadedCatalog =
    imageCatalogState?.type === "LOADED" ? imageCatalogState.data : null;
  const selectableImageEntries =
    loadedCatalog?.usable === true ? loadedCatalog.entries : [];
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
    { value: IMAGE_GENERATION_DEFAULT_VALUE, label: t("imageModelDefault") },
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
  const syncImageCatalogButton =
    integrationId != null && canSyncImageCatalog ? (
      <Button
        size="xs"
        variant="light"
        onClick={() => void onSyncImageCatalog(integrationId)}
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
  } else if (imageCatalogState.type === "LOADING") {
    imageCatalogNotice = (
      <Alert color="blue" title={t("imageCatalogLoadingTitle")}>
        {t("imageCatalogLoadingDescription")}
      </Alert>
    );
  } else if (imageCatalogState.type === "ERROR") {
    imageCatalogNotice = (
      <Alert color="orange" title={t("imageCatalogErrorTitle")}>
        <Stack gap="xs">
          <Text size="sm">{t("imageCatalogErrorDescription")}</Text>
          {syncImageCatalogButton}
        </Stack>
      </Alert>
    );
  } else if (imageCatalogState.type === "LOADED") {
    const catalog = imageCatalogState.data;
    if (!catalog.default_available) {
      imageCatalogNotice = (
        <Alert color="red" title={t("imageDefaultUnavailableTitle")}>
          {t("imageDefaultUnavailableDescription")}
        </Alert>
      );
    } else if (catalog.last_success_at == null) {
      imageCatalogNotice = (
        <Alert color="blue" title={t("imageCatalogNeverSyncedTitle")}>
          <Stack gap="xs">
            <Text size="sm">{t("imageCatalogNeverSyncedDescription")}</Text>
            {syncImageCatalogButton}
          </Stack>
        </Alert>
      );
    } else if (!catalog.usable) {
      imageCatalogNotice = (
        <Alert color="orange" title={t("imageCatalogChangedTitle")}>
          <Stack gap="xs">
            <Text size="sm">{t("imageCatalogChangedDescription")}</Text>
            {syncImageCatalogButton}
          </Stack>
        </Alert>
      );
    } else if (catalog.latest_sync?.status === "failed") {
      imageCatalogNotice = (
        <Alert color="yellow" title={t("imageCatalogLastSyncFailedTitle")}>
          <Stack gap="xs">
            <Text size="sm">{t("imageCatalogLastSyncFailedDescription")}</Text>
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
        label,
        model: candidate.model_display_name ?? t("noModelSelected"),
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
          value={candidate.context_window_tokens ?? ""}
          onChange={(value) =>
            onChange({
              ...candidate,
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
          value={candidate.max_output_tokens ?? ""}
          onChange={(value) =>
            onChange({
              ...candidate,
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
              value={candidate.builtin_tools}
              onChange={(builtinTools) => {
                const builtinToolConfigs = {
                  ...candidate.builtin_tool_configs,
                };
                for (const toolName of Object.keys(builtinToolConfigs)) {
                  if (!builtinTools.includes(toolName)) {
                    delete builtinToolConfigs[toolName];
                  }
                }
                onChange({
                  ...candidate,
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
          {imageModelSelectionVisible ? (
            <Box ml="xl">
              <Stack gap="xs">
                <Select
                  label={t("imageModelLabel")}
                  description={t("imageModelDescription")}
                  data={imageModelData}
                  value={selectedImageModelValue}
                  allowDeselect={false}
                  error={imageModelError}
                  onChange={(imageGenerationModel) => {
                    if (imageGenerationModel == null) {
                      return;
                    }
                    if (
                      imageGenerationModel === IMAGE_GENERATION_DEFAULT_VALUE
                    ) {
                      onChange(
                        withImageGenerationModelIdentifier(candidate, null),
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
                          candidate,
                          imageGenerationModel,
                        ),
                      );
                    }
                  }}
                />
                <Text c="dimmed" size="xs">
                  {imageModelDescription}
                </Text>
                {selectedImageModelAvailability === "UNAVAILABLE" ? (
                  <Alert color="orange" title={t("imageModelUnavailableTitle")}>
                    {t("imageModelUnavailableDescription")}
                  </Alert>
                ) : selectedImageModelAvailability === "UNVERIFIED" ? (
                  <Alert color="orange" title={t("imageModelUnverifiedTitle")}>
                    {t("imageModelUnverifiedDescription")}
                  </Alert>
                ) : null}
                {imageCatalogNotice}
              </Stack>
            </Box>
          ) : null}
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

interface LabelSettingsModalProps {
  option: SelectableModelOptionFormValue;
  opened: boolean;
  onClose: () => void;
  onChange: (option: SelectableModelOptionFormValue) => void;
}

function LabelSettingsModal({
  option,
  opened,
  onClose,
  onChange,
}: LabelSettingsModalProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("labelSettingsTitle", { label: option.label || t("newOption") })}
      centered
    >
      <Stack gap="md">
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
  title,
  description,
  options,
  defaultReasoningEffortControl,
  canEdit,
  showValidationErrors = false,
  imageGenerationCatalogStates,
  canSyncImageCatalog,
  onSyncImageCatalog,
  onChangeMainModelLabel,
  onChangeLightweightModelLabel,
  controller,
  modelPicker,
  OptionCardComponent,
}: SelectableModelOptionsEditorViewProps): React.ReactElement {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const {
    settingsTarget,
    settings,
    labelSettingsOption,
    copyNotice,
    sensors,
    labelOptions,
    optionIds,
    mainLabelValue,
    lightweightLabelValue,
    hasEmptyLabels,
    hasMissingModels,
    hasDuplicateLabels,
    hasDuplicateCandidates,
    hasInvalidImageGenerationSelection,
    setSettingsTarget,
    setLabelSettingsOptionId,
    setPickerTarget,
    clearCopyNotice,
    setLabelInputRef,
    handleChangeOptions,
    handleAddOption,
    handleAddCandidate,
    handleDragEnd,
    handleCopyPrimarySettings,
  } = controller;

  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Text fw={500}>{title}</Text>
        <Text size="sm" c="dimmed">
          {description}
        </Text>
        {showValidationErrors && options.length === 0 ? (
          <Alert color="red">{t("emptyList")}</Alert>
        ) : null}
        {options.length >= MAX_SELECTABLE_MODEL_OPTIONS ? (
          <Alert color="blue">{t("maxOptions")}</Alert>
        ) : null}
        {showValidationErrors && hasEmptyLabels ? (
          <Alert color="red">{t("emptyLabel")}</Alert>
        ) : null}
        {showValidationErrors && hasDuplicateLabels ? (
          <Alert color="red">{t("duplicateLabel")}</Alert>
        ) : null}
        {showValidationErrors && hasMissingModels ? (
          <Alert color="red">{t("missingModel")}</Alert>
        ) : null}
        {showValidationErrors && hasDuplicateCandidates ? (
          <Alert color="red">{t("duplicateCandidate")}</Alert>
        ) : null}
        {showValidationErrors && hasInvalidImageGenerationSelection ? (
          <Alert color="red">{t("invalidImageModel")}</Alert>
        ) : null}
        {copyNotice != null ? (
          <Alert color="blue" withCloseButton onClose={clearCopyNotice}>
            {t(copyNotice.key, { omitted: copyNotice.omitted })}
          </Alert>
        ) : null}
      </Stack>

      {modelPicker}

      {settings != null ? (
        <SelectableModelSettingsModal
          opened={settingsTarget != null}
          label={settings.option.label || t("newOption")}
          candidate={settings.candidate}
          imageGenerationCatalogStates={imageGenerationCatalogStates}
          canSyncImageCatalog={canSyncImageCatalog}
          onClose={() => setSettingsTarget(null)}
          onChange={(candidate) => {
            if (settingsTarget == null) {
              return;
            }
            handleChangeOptions(
              updateCandidate(options, settingsTarget, () => candidate),
            );
          }}
          onSyncImageCatalog={onSyncImageCatalog}
        />
      ) : null}

      {labelSettingsOption != null ? (
        <LabelSettingsModal
          opened
          option={labelSettingsOption}
          onClose={() => setLabelSettingsOptionId(null)}
          onChange={(option) =>
            handleChangeOptions(updateOption(options, option.id, () => option))
          }
        />
      ) : null}

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

      {options.length > 0 ? (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={optionIds}
            strategy={verticalListSortingStrategy}
          >
            <Stack gap="sm">
              {options.map((option, index) => (
                <OptionCardComponent
                  key={option.id}
                  option={option}
                  duplicateLabel={rowHasDuplicateLabel(options, index)}
                  canEdit={canEdit}
                  canRemove={options.length > 1}
                  showValidationErrors={showValidationErrors}
                  labelInputRef={(node) => setLabelInputRef(option.id, node)}
                  onChangeLabel={(label) =>
                    handleChangeOptions(
                      updateOption(options, option.id, (current) => ({
                        ...current,
                        label,
                      })),
                    )
                  }
                  onOpenLabelSettings={() =>
                    setLabelSettingsOptionId(option.id)
                  }
                  onAddCandidate={() => handleAddCandidate(option)}
                  onChangeCandidateModel={(candidateId) =>
                    setPickerTarget({ optionId: option.id, candidateId })
                  }
                  onOpenCandidateSettings={(candidateId) =>
                    setSettingsTarget({ optionId: option.id, candidateId })
                  }
                  onCopyPrimarySettings={(candidateId) =>
                    handleCopyPrimarySettings(option, candidateId)
                  }
                  onMoveCandidate={(candidateId, direction) => {
                    const candidateIndex = option.candidates.findIndex(
                      (candidate) => candidate.id === candidateId,
                    );
                    const targetIndex = candidateIndex + direction;
                    if (
                      candidateIndex < 0 ||
                      targetIndex < 0 ||
                      targetIndex >= option.candidates.length
                    ) {
                      return;
                    }
                    handleChangeOptions(
                      updateOption(options, option.id, (current) => ({
                        ...current,
                        candidates: arrayMove(
                          current.candidates,
                          candidateIndex,
                          targetIndex,
                        ),
                      })),
                    );
                  }}
                  onRemoveCandidate={(candidateId) =>
                    handleChangeOptions(
                      updateOption(options, option.id, (current) => ({
                        ...current,
                        candidates: current.candidates.filter(
                          (candidate) => candidate.id !== candidateId,
                        ),
                      })),
                    )
                  }
                  onRemoveOption={() =>
                    handleChangeOptions(
                      options.filter((item) => item.id !== option.id),
                    )
                  }
                />
              ))}
            </Stack>
          </SortableContext>
        </DndContext>
      ) : null}
      <Divider />
    </Stack>
  );
}
