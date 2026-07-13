export type LoginState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string };
