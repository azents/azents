import type {
  RoutineDefinitionResponse,
  RoutineDetailResponse,
} from "@azents/public-client";

export type SessionRoutinesState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: RoutineDefinitionResponse[] };

export type RoutineDetailState =
  | { type: "NONE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; data: RoutineDetailResponse };
