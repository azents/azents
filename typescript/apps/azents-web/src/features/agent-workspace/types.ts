import type { AgentWorkspaceResponse } from "@azents/public-client";

export type ProjectDirectoryPickerEntry = {
  path: string;
  kind: "file" | "directory";
  repositoryType?: "git" | null;
};

export type ProjectDirectoryPickerState =
  | { type: "CLOSED" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "SERVER";
      server: AgentWorkspaceResponse;
      currentPath: string;
      entries: ProjectDirectoryPickerEntry[];
      isRefreshing: boolean;
      isStarting: boolean;
    };
