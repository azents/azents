/**
 * ADT definitions for the users feature
 */

// --- API response types (re-exported from the generated client) ---
export type { UserEmailResponse, UserResponse } from "@azents/admin-client";

import type { UserResponse } from "@azents/admin-client";

// --- ADT state types ---

/** User list state */
export type UserListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      users: UserResponse[];
    };

/** System administrator role state */
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
