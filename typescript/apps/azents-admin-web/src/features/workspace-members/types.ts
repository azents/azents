/**
 * Workspace Members Feature - ADT (Algebraic Data Types) 정의
 */

// --- API 응답 타입 (generated client에서 re-export) ---
export type {
  WorkspaceUserResponse,
  WorkspaceUserRole,
} from "@azents/admin-client";

import type { WorkspaceUserResponse } from "@azents/admin-client";

// --- ADT 상태 타입 ---

/** WorkspaceMember 목록 상태 */
export type WorkspaceMemberListState =
  | { type: "NO_WORKSPACE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      members: WorkspaceUserResponse[];
    };

/** WorkspaceMember 상세 상태 */
export type WorkspaceMemberDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; memberId: string }
  | { type: "ERROR"; memberId: string; message: string }
  | { type: "VIEWING"; member: WorkspaceUserResponse }
  | { type: "DELETING"; member: WorkspaceUserResponse };
