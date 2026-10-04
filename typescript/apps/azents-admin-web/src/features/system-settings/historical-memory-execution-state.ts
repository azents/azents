import type { HistoricalMemoryExecutionDraft } from "./types";
import type { HistoricalMemoryExecutionDetailResponse } from "@azents/admin-client";

export type HistoricalMemoryExecutionValues =
  | { type: "INVALID" }
  | { type: "VALID"; maxTurns: number | null; timeoutSeconds: number };

export interface HistoricalMemoryExecutionForm {
  baseline: HistoricalMemoryExecutionDetailResponse;
  draft: HistoricalMemoryExecutionDraft;
  newerVersion: number | null;
}

export interface HistoricalMemoryExecutionSaveInput {
  expectedVersion: number;
  maxTurns: number | null;
  timeoutSeconds: number;
}

export function isPositiveInteger(value: number | string): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function historicalMemoryExecutionDraft(
  detail: HistoricalMemoryExecutionDetailResponse,
): HistoricalMemoryExecutionDraft {
  return {
    maxTurns: detail.max_turns ?? "",
    timeoutSeconds: detail.timeout_seconds,
  };
}

export function historicalMemoryExecutionValues(
  draft: HistoricalMemoryExecutionDraft,
): HistoricalMemoryExecutionValues {
  if (
    (draft.maxTurns !== "" && !isPositiveInteger(draft.maxTurns)) ||
    !isPositiveInteger(draft.timeoutSeconds)
  ) {
    return { type: "INVALID" };
  }
  return {
    type: "VALID",
    maxTurns: draft.maxTurns === "" ? null : draft.maxTurns,
    timeoutSeconds: draft.timeoutSeconds,
  };
}

export function historicalMemoryExecutionDirty(
  draft: HistoricalMemoryExecutionDraft,
  detail: HistoricalMemoryExecutionDetailResponse,
): boolean {
  const current = historicalMemoryExecutionDraft(detail);
  return (
    draft.maxTurns !== current.maxTurns ||
    draft.timeoutSeconds !== current.timeoutSeconds
  );
}

export function loadHistoricalMemoryExecutionForm(
  detail: HistoricalMemoryExecutionDetailResponse,
): HistoricalMemoryExecutionForm {
  return {
    baseline: detail,
    draft: historicalMemoryExecutionDraft(detail),
    newerVersion: null,
  };
}

export function receiveHistoricalMemoryExecutionDetail(
  form: HistoricalMemoryExecutionForm | null,
  detail: HistoricalMemoryExecutionDetailResponse,
): HistoricalMemoryExecutionForm {
  if (form === null) {
    return loadHistoricalMemoryExecutionForm(detail);
  }
  if (detail.admin_version <= form.baseline.admin_version) {
    return form;
  }
  if (
    form.newerVersion !== null ||
    historicalMemoryExecutionDirty(form.draft, form.baseline)
  ) {
    return {
      ...form,
      newerVersion: Math.max(form.newerVersion ?? 0, detail.admin_version),
    };
  }
  return loadHistoricalMemoryExecutionForm(detail);
}

export function editHistoricalMemoryExecutionForm(
  form: HistoricalMemoryExecutionForm,
  draft: HistoricalMemoryExecutionDraft,
): HistoricalMemoryExecutionForm {
  return { ...form, draft };
}

export function historicalMemoryExecutionSaveInput(
  form: HistoricalMemoryExecutionForm,
): HistoricalMemoryExecutionSaveInput | null {
  const values = historicalMemoryExecutionValues(form.draft);
  if (values.type === "INVALID") {
    return null;
  }
  return {
    expectedVersion: form.baseline.admin_version,
    maxTurns: values.maxTurns,
    timeoutSeconds: values.timeoutSeconds,
  };
}

export function historicalMemoryExecutionConflict(
  form: HistoricalMemoryExecutionForm | null,
  mutationErrorCode: string | null,
): boolean {
  return mutationErrorCode === "CONFLICT" || form?.newerVersion != null;
}
