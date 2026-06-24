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

/** Elevation modal state */
export type ElevationState =
  | { type: "CHOOSE_METHOD"; methods: AuthMethod[] }
  | { type: "EMAIL_SENDING" }
  | {
      type: "EMAIL_CODE";
      csrfToken: string;
      sentAt: number;
      error: string | null;
    }
  | { type: "EMAIL_VERIFYING"; csrfToken: string; sentAt: number }
  | { type: "PASSWORD_INPUT"; error: string | null }
  | { type: "PASSWORD_VERIFYING" };

/** Password management state */
export type PasswordManageState =
  | { type: "IDLE"; error: string | null }
  | { type: "SAVING" };
