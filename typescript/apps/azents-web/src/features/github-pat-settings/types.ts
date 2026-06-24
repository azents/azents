/**
 * GitHub PAT settings ADT type.
 */

/** PAT registration state */
export type PatStatus =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "NOT_REGISTERED";
    }
  | {
      type: "REGISTERED";
      githubUsername: string;
      displayHint: string | null;
      expiresAt: string | null;
    };

/** Settings page state */
export type SetupPageState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "PAT_FORM" }
  | {
      type: "DONE";
      githubUsername: string;
    };
