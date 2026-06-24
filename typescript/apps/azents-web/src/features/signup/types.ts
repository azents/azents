export type SignupState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "INVALID"; message: string }
  | {
      type: "READY";
      emailHint: string;
      error: string | null;
      submitting: boolean;
    }
  | { type: "SUCCESS" };

export interface SignupPageProps {
  token: string;
}
