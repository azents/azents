/**
 * Workspaces Feature - ADT (Algebraic Data Types) 정의
 */

// --- API 응답 타입 (generated client에서 re-export) ---
export type { WorkspaceResponse } from "@azents/admin-client";

import type { WorkspaceResponse } from "@azents/admin-client";

// --- 폼 데이터 타입 ---
export interface WorkspaceFormData {
  name: string;
  handle: string;
}

// --- 변환 함수 ---

/** API 응답 → 폼 데이터 변환 */
export function workspaceToFormData(
  workspace: WorkspaceResponse,
): WorkspaceFormData {
  return {
    name: workspace.name,
    handle: workspace.handle,
  };
}

/** 폼 데이터 → API 요청 변환 (생성용) */
export function formDataToCreateRequest(data: WorkspaceFormData): {
  name: string;
  handle: string;
} {
  return {
    name: data.name,
    handle: data.handle,
  };
}

/** 폼 데이터 → API 요청 변환 (수정용) */
export function formDataToUpdateRequest(data: WorkspaceFormData): {
  name: string;
  handle: string;
} {
  return {
    name: data.name,
    handle: data.handle,
  };
}

// --- ADT 상태 타입 ---

/** Workspace 목록 상태 */
export type WorkspaceListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; workspaces: WorkspaceResponse[] };

/** Workspace 상세 상태 */
export type WorkspaceDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; handle: string }
  | { type: "ERROR"; handle: string; message: string }
  | { type: "EDITING"; workspace: WorkspaceResponse | null; isNew: boolean }
  | { type: "SAVING"; workspace: WorkspaceResponse | null; isNew: boolean };
