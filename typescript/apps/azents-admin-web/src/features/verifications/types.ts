/**
 * ADT definitions for the verifications feature
 */

// --- API response types (re-exported from the generated client) ---
export type { EmailVerificationResponse } from "@azents/admin-client";

import type { EmailVerificationResponse } from "@azents/admin-client";

// --- ADT state types ---

/** Verification list state */
export type VerificationListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      verifications: EmailVerificationResponse[];
    };

/** Verification detail state */
export type VerificationDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; verificationId: string }
  | { type: "ERROR"; verificationId: string; message: string }
  | {
      type: "LOADED";
      verification: EmailVerificationResponse;
    };
