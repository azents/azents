export type BootstrapState =
  | { type: "LOADING" }
  | { type: "UNAVAILABLE" }
  | { type: "READY"; error: string | null; submitting: boolean }
  | { type: "SUCCESS" };

export interface BootstrapFormValues {
  email: string;
  password: string;
  ownerName: string;
  workspaceName: string;
  workspaceHandle: string;
}
