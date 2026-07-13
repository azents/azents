/**
 * Users Feature - ADT (Algebraic Data Types) 정의
 */

// --- API 응답 타입 (generated client에서 re-export) ---
export type { UserEmailResponse, UserResponse } from "@azents/admin-client";

import type { UserResponse } from "@azents/admin-client";

// --- ADT 상태 타입 ---

/** User 목록 상태 */
export type UserListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      users: UserResponse[];
    };

/** User 상세 상태 */
export type SystemAdminRoleState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      assigned: boolean;
      currentUser: boolean;
      finalAdmin: boolean;
      action: "IDLE" | "GRANTING" | "REVOKING";
    };

export type UserDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; userId: string }
  | { type: "ERROR"; userId: string; message: string }
  | {
      type: "VIEWING";
      user: UserResponse;
    }
  | {
      type: "DELETING";
      user: UserResponse;
    };
