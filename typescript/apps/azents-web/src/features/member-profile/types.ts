/**
 * Member profile edit page ADT state type
 */

/** Member profile data */
export interface MemberProfile {
  id: string;
  name: string;
  locale: string;
  role: string;
  createdAt: string;
  updatedAt: string;
}

/** Profile edit form state */
export type FormState =
  | { type: "IDLE" }
  | { type: "SUBMITTING" }
  | { type: "SUCCESS" }
  | { type: "ERROR"; message: string };

/** Entire page state */
export type MemberProfileState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      profile: MemberProfile;
      formState: FormState;
    };
