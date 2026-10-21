import type { AuthMethod } from "@azents/public-client";

/** Shared step-up challenge states used by security and account-link surfaces. */
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
