export type LoginMode = "LOGIN" | "BOOTSTRAP";

export type LoginState =
  | { type: "LOADING" }
  | { type: "READY"; mode: LoginMode }
  | { type: "SUBMITTING"; mode: LoginMode }
  | { type: "ERROR"; mode: LoginMode; message: string };
