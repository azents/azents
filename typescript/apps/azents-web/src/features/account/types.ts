/**
 * Account settings page ADT state type
 */

export type AccountState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      email: string;
      locale: string;
      createdAt: Date;
    };
