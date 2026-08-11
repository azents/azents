import type {
  AgentRuntimeResponse,
  AgentWorkspaceResponse,
} from "@azents/public-client";

export type ProjectDirectoryPickerEntry = {
  path: string;
  kind: "file" | "directory";
  repositoryType?: "git" | null;
};

export type ProjectDirectoryPickerState =
  | { type: "CLOSED" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "RUNTIME_FREE"; runtime: AgentRuntimeResponse }
  | { type: "REMOVING"; runtime: AgentRuntimeResponse }
  | {
      type: "SERVER";
      server: AgentWorkspaceResponse;
      currentPath: string;
      entries: ProjectDirectoryPickerEntry[];
      isRefreshing: boolean;
      isStarting: boolean;
    };
