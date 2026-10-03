import type {
  SelectableModelCandidateFormValue,
  SelectableModelOptionFormValue,
} from "./model-selection";

export interface CandidateTarget {
  optionId: string;
  candidateId: string;
}

export interface EditorCandidate {
  option: SelectableModelOptionFormValue;
  candidate: SelectableModelCandidateFormValue;
  candidateIndex: number;
}

export function createEditorId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function rowHasDuplicateLabel(
  options: SelectableModelOptionFormValue[],
  rowIndex: number,
): boolean {
  const label = options[rowIndex]?.label.trim() ?? "";
  return (
    label.length > 0 &&
    options.some(
      (option, index) => index !== rowIndex && option.label.trim() === label,
    )
  );
}

export function candidateHasDuplicateModel(
  option: SelectableModelOptionFormValue,
  candidateIndex: number,
): boolean {
  const value = option.candidates[candidateIndex]?.model_selection_value;
  return (
    value != null &&
    option.candidates.some(
      (candidate, index) =>
        index !== candidateIndex && candidate.model_selection_value === value,
    )
  );
}

export function updateOption(
  options: SelectableModelOptionFormValue[],
  id: string,
  update: (
    option: SelectableModelOptionFormValue,
  ) => SelectableModelOptionFormValue,
): SelectableModelOptionFormValue[] {
  return options.map((option) => (option.id === id ? update(option) : option));
}

export function updateCandidate(
  options: SelectableModelOptionFormValue[],
  target: CandidateTarget,
  update: (
    candidate: SelectableModelCandidateFormValue,
  ) => SelectableModelCandidateFormValue,
): SelectableModelOptionFormValue[] {
  return updateOption(options, target.optionId, (option) => ({
    ...option,
    candidates: option.candidates.map((candidate) =>
      candidate.id === target.candidateId ? update(candidate) : candidate,
    ),
  }));
}

export function findCandidate(
  options: SelectableModelOptionFormValue[],
  target: CandidateTarget | null,
): EditorCandidate | null {
  if (target == null) {
    return null;
  }
  const option = options.find((item) => item.id === target.optionId);
  if (option == null) {
    return null;
  }
  const candidateIndex = option.candidates.findIndex(
    (candidate) => candidate.id === target.candidateId,
  );
  const candidate = option.candidates[candidateIndex];
  return candidate == null ? null : { option, candidate, candidateIndex };
}
