import type { RuntimeWebServiceResponse } from "@azents/public-client";

export type RuntimeWebAction = "approve" | "reject" | "cancel" | "close" | null;

export type RuntimeWebConfirmationState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      service: RuntimeWebServiceResponse;
      action: RuntimeWebAction;
      actionError: string | null;
    };
