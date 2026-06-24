import type {
  CreatePasswordResetTokenResponse,
  PasswordResetTokenResponse,
} from "@azents/admin-client";

export type PasswordResetAdminState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: PasswordResetTokenResponse[] };

export type CreatedPasswordResetToken = CreatePasswordResetTokenResponse;
