import type { ApiErrorProjection } from "@/trpc/api-error";
import type { AutomaticSessionProjectsResponse } from "@azents/public-client";

export type ProjectPreviewStatus =
  | "unchecked"
  | "available"
  | "missing"
  | "unavailable"
  | "error";

export type AutomaticProjectRow = {
  path: string;
  name: string;
  status: ProjectPreviewStatus;
  detail: string | null;
};

export type AutomaticProjectsState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "EDITOR_ERROR";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
      message: string;
    }
  | { type: "EMPTY"; revision: number; updatedAt: string }
  | {
      type: "CLEAN";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
    }
  | {
      type: "DIRTY";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
    }
  | {
      type: "SAVING";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
    }
  | {
      type: "RUNTIME_UNAVAILABLE";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
      message: string;
    }
  | {
      type: "MISSING";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
      message: string;
      dirty: boolean;
    }
  | {
      type: "VALIDATION_ERROR";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
      message: string;
      path: string | null;
    }
  | {
      type: "CONFLICT";
      revision: number;
      rows: AutomaticProjectRow[];
      updatedAt: string;
      message: string;
    };

export interface AutomaticProjectsStateInputs {
  policyLoading: boolean;
  policyLoaded: boolean;
  policyError: string | null;
  draftInitialized: boolean;
  mutationPending: boolean;
  revision: number;
  rows: AutomaticProjectRow[];
  updatedAt: string;
  dirty: boolean;
  saveError: {
    code: string | null;
    message: string;
    path: string | null;
  } | null;
}

export interface AutomaticProjectsBaseline {
  revision: number;
  paths: string[];
  updatedAt: string;
}

interface CommitAutomaticProjectsReplacementInput {
  mutate: () => Promise<AutomaticSessionProjectsResponse>;
  setPolicyData: (response: AutomaticSessionProjectsResponse) => void;
  invalidatePolicy: () => Promise<void>;
  invalidatePreview: () => Promise<void>;
}

interface FetchLatestAutomaticProjectsInput {
  invalidatePolicy: () => Promise<void>;
  fetchPolicy: () => Promise<AutomaticSessionProjectsResponse>;
}

export function automaticProjectsBaseline(
  response: AutomaticSessionProjectsResponse,
): AutomaticProjectsBaseline {
  return {
    revision: response.revision,
    paths: dedupeProjectPaths(response.project_paths),
    updatedAt: response.updated_at,
  };
}

export function initializeAutomaticProjectsBaseline(
  current: AutomaticProjectsBaseline | null,
  response: AutomaticSessionProjectsResponse,
): AutomaticProjectsBaseline {
  return current ?? automaticProjectsBaseline(response);
}

export async function commitAutomaticProjectsReplacement({
  mutate,
  setPolicyData,
  invalidatePolicy,
  invalidatePreview,
}: CommitAutomaticProjectsReplacementInput): Promise<AutomaticProjectsBaseline> {
  const response = await mutate();
  const baseline = automaticProjectsBaseline(response);
  setPolicyData(response);
  await Promise.all([invalidatePolicy(), invalidatePreview()]);
  return baseline;
}

export async function fetchLatestAutomaticProjects({
  invalidatePolicy,
  fetchPolicy,
}: FetchLatestAutomaticProjectsInput): Promise<AutomaticProjectsBaseline> {
  await invalidatePolicy();
  return automaticProjectsBaseline(await fetchPolicy());
}

export function automaticProjectsErrorProjection(
  error: unknown,
): ApiErrorProjection | null {
  if (typeof error !== "object" || error === null || !("data" in error)) {
    return null;
  }
  const data = error.data;
  if (typeof data !== "object" || data === null || !("apiError" in data)) {
    return null;
  }
  const value = data.apiError;
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const code = "code" in value ? value.code : null;
  const message = "message" in value ? value.message : null;
  const path = "path" in value ? value.path : null;
  return {
    code: typeof code === "string" ? code : null,
    message: typeof message === "string" ? message : "Request failed.",
    path: typeof path === "string" ? path : null,
  };
}

export function automaticProjectsEditingDisabled(
  state: AutomaticProjectsState,
): boolean {
  return state.type === "SAVING";
}

export function automaticProjectsSaveEnabled(
  state: AutomaticProjectsState,
): boolean {
  return (
    state.type === "DIRTY" ||
    (state.type === "MISSING" && state.dirty) ||
    state.type === "EDITOR_ERROR"
  );
}

export function deriveAutomaticProjectsState({
  policyLoading,
  policyLoaded,
  policyError,
  draftInitialized,
  mutationPending,
  revision,
  rows,
  updatedAt,
  dirty,
  saveError,
}: AutomaticProjectsStateInputs): AutomaticProjectsState {
  if (policyError) {
    return { type: "ERROR", message: policyError };
  }
  if (policyLoading || !policyLoaded || !draftInitialized) {
    return { type: "LOADING" };
  }
  if (mutationPending) {
    return { type: "SAVING", revision, rows, updatedAt };
  }
  if (saveError?.code === "automatic_session_projects_revision_conflict") {
    return {
      type: "CONFLICT",
      revision,
      rows,
      updatedAt,
      message: saveError.message,
    };
  }
  if (saveError?.code === "automatic_session_projects_runtime_unavailable") {
    return {
      type: "RUNTIME_UNAVAILABLE",
      revision,
      rows,
      updatedAt,
      message: saveError.message,
    };
  }
  if (saveError?.code === "automatic_session_projects_invalid_path") {
    return {
      type: "VALIDATION_ERROR",
      revision,
      rows,
      updatedAt,
      message: saveError.message,
      path: saveError.path,
    };
  }
  if (saveError) {
    return {
      type: "EDITOR_ERROR",
      revision,
      rows,
      updatedAt,
      message: saveError.message,
    };
  }
  if (rows.some((row) => row.status === "missing")) {
    return {
      type: "MISSING",
      revision,
      rows,
      updatedAt,
      message: "",
      dirty,
    };
  }
  if (rows.length === 0 && !dirty) {
    return { type: "EMPTY", revision, updatedAt };
  }
  return { type: dirty ? "DIRTY" : "CLEAN", revision, rows, updatedAt };
}

export function normalizeProjectPath(path: string): string {
  if (path === "/") {
    return path;
  }
  return path.replace(/\/+$/, "");
}

export function dedupeProjectPaths(paths: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const path of paths) {
    const normalized = normalizeProjectPath(path);
    if (normalized === "" || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

export function projectBasename(path: string): string {
  const normalized = normalizeProjectPath(path);
  return normalized.slice(normalized.lastIndexOf("/") + 1) || normalized;
}
