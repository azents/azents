/**
 * ADT state for each Auth step
 *
 * Each page has its own state type.
 * Explicitly define all possible states.
 */

/** Login step: Email input */
export type LoginState =
  | { type: "IDLE"; error: string | null }
  | { type: "CHECKING_METHODS" }
  | { type: "SENDING" };

/** Verification code validation step */
export type VerifyState =
  | { type: "IDLE"; email: string; sentAt: number; error: string | null }
  | { type: "VERIFYING"; email: string; sentAt: number };

/** Password login step */
export type PasswordLoginState =
  | { type: "IDLE"; email: string; error: string | null }
  | { type: "SUBMITTING"; email: string };
