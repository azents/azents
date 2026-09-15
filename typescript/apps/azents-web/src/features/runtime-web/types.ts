import type { RuntimeWebServiceResponse } from "@azents/public-client";

export type RuntimeWebDurationSeconds = 3600 | 21_600 | 86_400;

export type RuntimeWebServicesState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      services: RuntimeWebServiceResponse[];
      runtimeAvailable: boolean;
    };

export type RuntimeWebMutationAction =
  "create" | "update" | "turnOn" | "turnOff" | "reset" | "delete" | null;

export type RuntimeWebActivationState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      service: RuntimeWebServiceResponse;
      action: "turnOn" | null;
      actionError: string | null;
    };
