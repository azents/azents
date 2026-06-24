import type { SignupTokenResponse } from "@azents/admin-client";

export type SignupTokenAdminState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; tokens: SignupTokenResponse[] };

export type SignupTokenCreateState =
  | { type: "IDLE"; error: string | null }
  | { type: "CREATING" };

export interface CreatedSignupTokenState {
  email: string;
  signupUrl: string;
}
