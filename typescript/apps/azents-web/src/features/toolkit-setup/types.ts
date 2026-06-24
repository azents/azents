/**
 * Toolkit setup redirect state ADT.
 */
export type ToolkitSetupState =
  | { type: "REDIRECTING" }
  | { type: "ERROR"; message: string };
