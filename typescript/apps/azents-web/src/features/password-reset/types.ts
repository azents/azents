import type { PreviewPasswordResetTokenResponse } from "@azents/public-client";

export type PasswordResetState =
  | { type: "LOADING" }
  | { type: "INVALID" }
  | { type: "READY"; preview: PreviewPasswordResetTokenResponse }
  | { type: "SAVING"; preview: PreviewPasswordResetTokenResponse }
  | { type: "SUCCESS" }
  | { type: "ERROR"; message: string };
