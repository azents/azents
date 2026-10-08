/**
 * ADT state for each Auth step
 *
 * Each page has its own state type.
 * Explicitly define all possible states.
 */

import type { FormEvent, RefObject } from "react";

/** Login step: Email input */
export type LoginState =
  | { type: "IDLE"; error: string | null }
  | { type: "SUBMITTING" }
  | { type: "CHECKING_METHODS" }
  | { type: "SENDING" };

/** Transient login actions supplied by the API container or story fixture. */
export interface LoginStepActions {
  emailAvailable: boolean;
  onSubmit: (email: string, password: string) => void;
  onRequestSignupEmail: (email: string) => void;
}

/** Form state and DOM synchronization owned by the login form container. */
export interface LoginStepFormState {
  formRef: RefObject<HTMLFormElement | null>;
  emailValid: boolean;
  passwordPresent: boolean;
  onInput: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onRequestSignupEmail: () => void;
}

export interface LoginStepContainerProps extends LoginStepActions {
  state: LoginState;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  form: LoginStepFormState;
}

/** Verification code validation step */
export type VerifyState =
  | { type: "IDLE"; email: string; sentAt: number; error: string | null }
  | { type: "VERIFYING"; email: string; sentAt: number };

/** Password login step */
export type PasswordLoginState =
  | { type: "IDLE"; email: string; error: string | null }
  | { type: "SUBMITTING"; email: string };
