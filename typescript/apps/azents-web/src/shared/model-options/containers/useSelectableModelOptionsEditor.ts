"use client";

import {
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove, sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  candidateHasDuplicateModel,
  createEditorId,
  findCandidate,
  rowHasDuplicateLabel,
  updateCandidate,
} from "../model-option-editor";
import {
  copyCompatiblePrimarySettings,
  createSelectableModelCandidateFormValue,
  createSelectableModelOptionFormValue,
  fallbackSelectableModelLabel,
  hasInvalidImageGenerationSelections,
  MAX_SELECTABLE_MODEL_CANDIDATES,
  MAX_SELECTABLE_MODEL_OPTIONS,
  selectableModelLabelSelectData,
} from "../model-selection";
import type { SelectableModelOptionsEditorProps } from "../components/SelectableModelOptionsEditor";
import type { CandidateTarget, EditorCandidate } from "../model-option-editor";
import type { SelectableModelOptionFormValue } from "../model-selection";
import type { DragEndEvent } from "@dnd-kit/core";

export interface SelectableModelOptionsEditorController {
  pickerTarget: CandidateTarget | null;
  settingsTarget: CandidateTarget | null;
  picker: EditorCandidate | null;
  settings: EditorCandidate | null;
  labelSettingsOption: SelectableModelOptionFormValue | null;
  copyNotice: {
    key: "copyPrimaryComplete" | "copyPrimaryPartial";
    omitted: string;
  } | null;
  sensors: ReturnType<typeof useSensors>;
  labelOptions: Array<{ value: string; label: string }>;
  optionIds: string[];
  mainLabelValue: string | null;
  lightweightLabelValue: string | null;
  hasEmptyLabels: boolean;
  hasMissingModels: boolean;
  hasDuplicateLabels: boolean;
  hasDuplicateCandidates: boolean;
  hasInvalidImageGenerationSelection: boolean;
  setPickerTarget: (target: CandidateTarget | null) => void;
  setSettingsTarget: (target: CandidateTarget | null) => void;
  setLabelSettingsOptionId: (id: string | null) => void;
  clearCopyNotice: () => void;
  setLabelInputRef: (id: string, node: HTMLInputElement | null) => void;
  handleChangeOptions: (options: SelectableModelOptionFormValue[]) => void;
  handleAddOption: () => void;
  handleAddCandidate: (option: SelectableModelOptionFormValue) => void;
  handleDragEnd: (event: DragEndEvent) => void;
  handleCopyPrimarySettings: (
    option: SelectableModelOptionFormValue,
    candidateId: string,
  ) => void;
}

export function useSelectableModelOptionsEditor({
  options,
  mainModelLabel,
  lightweightModelLabel,
  imageGenerationCatalogStates,
  onChangeOptions,
  onChangeMainModelLabel,
  onChangeLightweightModelLabel,
}: SelectableModelOptionsEditorProps): SelectableModelOptionsEditorController {
  const t = useTranslations("workspace.agents.selectableModelOptions");
  const [pickerTarget, setPickerTarget] = useState<CandidateTarget | null>(
    null,
  );
  const [settingsTarget, setSettingsTarget] = useState<CandidateTarget | null>(
    null,
  );
  const [labelSettingsOptionId, setLabelSettingsOptionId] = useState<
    string | null
  >(null);
  const [copyNotice, setCopyNotice] =
    useState<SelectableModelOptionsEditorController["copyNotice"]>(null);
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
  // Keep the same memoized label and ID arrays used by the previous editor.
  const labelOptions = useMemo(
    () => selectableModelLabelSelectData(options),
    [options],
  );
  const optionIds = useMemo(
    () => options.map((option) => option.id),
    [options],
  );
  const picker = findCandidate(options, pickerTarget);
  const settings = findCandidate(options, settingsTarget);
  const labelSettingsOption =
    options.find((option) => option.id === labelSettingsOptionId) ?? null;
  const mainLabelValue = fallbackSelectableModelLabel(mainModelLabel, options);
  const lightweightLabelValue = fallbackSelectableModelLabel(
    lightweightModelLabel,
    options,
  );
  const hasEmptyLabels = options.some((option) => option.label.trim() === "");
  const hasMissingModels = options.some(
    (option) =>
      option.candidates.length === 0 ||
      option.candidates.some(
        (candidate) => candidate.model_selection_value == null,
      ),
  );
  const hasDuplicateLabels = options.some((_, index) =>
    rowHasDuplicateLabel(options, index),
  );
  const hasDuplicateCandidates = options.some((option) =>
    option.candidates.some((_, index) =>
      candidateHasDuplicateModel(option, index),
    ),
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
    const id = createEditorId("option");
    setPendingFocusOptionId(id);
    handleChangeOptions([...options, createSelectableModelOptionFormValue(id)]);
  };
  const handleAddCandidate = (option: SelectableModelOptionFormValue): void => {
    if (option.candidates.length >= MAX_SELECTABLE_MODEL_CANDIDATES) {
      return;
    }
    const candidate = createSelectableModelCandidateFormValue(
      createEditorId(`${option.id}-candidate`),
    );
    handleChangeOptions(
      options.map((current) =>
        current.id === option.id
          ? { ...current, candidates: [...current.candidates, candidate] }
          : current,
      ),
    );
    setPickerTarget({ optionId: option.id, candidateId: candidate.id });
  };
  const handleDragEnd = ({ active, over }: DragEndEvent): void => {
    if (over == null || active.id === over.id) {
      return;
    }
    const activeIndex = options.findIndex(
      (option) => option.id === String(active.id),
    );
    const overIndex = options.findIndex(
      (option) => option.id === String(over.id),
    );
    if (activeIndex >= 0 && overIndex >= 0) {
      handleChangeOptions(arrayMove(options, activeIndex, overIndex));
    }
  };
  const handleCopyPrimarySettings = (
    option: SelectableModelOptionFormValue,
    candidateId: string,
  ): void => {
    const primary = option.candidates[0];
    const target = option.candidates.find(
      (candidate) => candidate.id === candidateId,
    );
    if (primary == null || target == null || primary.id === target.id) {
      return;
    }
    const copied = copyCompatiblePrimarySettings(primary, target);
    handleChangeOptions(
      updateCandidate(
        options,
        { optionId: option.id, candidateId },
        () => copied.candidate,
      ),
    );
    setCopyNotice({
      key:
        copied.omitted.length === 0
          ? "copyPrimaryComplete"
          : "copyPrimaryPartial",
      omitted: copied.omitted
        .map((item) => t(`copyOmitted.${item}`))
        .join(", "),
    });
  };
  return {
    pickerTarget,
    settingsTarget,
    picker,
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
    setPickerTarget,
    setSettingsTarget,
    setLabelSettingsOptionId,
    clearCopyNotice: () => setCopyNotice(null),
    setLabelInputRef: (id, node) => {
      if (node == null) {
        labelInputRefs.current.delete(id);
      } else {
        labelInputRefs.current.set(id, node);
      }
    },
    handleChangeOptions,
    handleAddOption,
    handleAddCandidate,
    handleDragEnd,
    handleCopyPrimarySettings,
  };
}
