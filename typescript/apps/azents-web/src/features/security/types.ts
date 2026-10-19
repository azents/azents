/**
 * Security page ADT state definition
 */

import type { AuthMethod } from "@azents/public-client";

/** Security page main state */
export type SecurityState =
  | { type: "LOADING" }
  | { type: "ELEVATION_REQUIRED"; elevationMethods: AuthMethod[] | null }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      methods: AuthMethod[];
      hasPassword: boolean;
    };

/** Password management state */
export type PasswordManageState =
  { type: "IDLE"; error: string | null } | { type: "SAVING" };
