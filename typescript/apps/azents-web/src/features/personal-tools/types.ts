import type {
  PersonalToolkitResponse,
  UploadedImage,
} from "@azents/public-client";

export type PersonalToolsState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; items: PersonalToolkitResponse[] };

export type PersonalWriteState =
  | { type: "IDLE" }
  | { type: "SAVING" }
  | { type: "SAVED" }
  | { type: "ERROR"; conflict: boolean };

export interface AccessChoice {
  id: string;
  name: string;
  detail: string | null;
  avatar?: UploadedImage | null;
  allowed: boolean;
}
export interface AccessGroup {
  id: string;
  name: string;
  items: AccessChoice[];
}
export type PersonalAccessState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      subject: string;
      account: string;
      groups: AccessGroup[];
      empty: boolean;
      mode: "all" | "selected" | null;
      firstRestriction: boolean;
    };

export type PersonalAccessTarget =
  | { type: "connection"; handle: string; toolkitId: string }
  | {
      type: "agent";
      handle: string;
      agentId: string;
      agentName: string;
      originSessionId?: string;
      setupHref?: string;
    };

export interface PersonalAccessProps {
  state: PersonalAccessState;
  target: PersonalAccessTarget["type"];
  handle: string;
  setupHref?: string;
  search: string;
  dirty: boolean;
  write: PersonalWriteState;
  onSearch: (search: string) => void;
  onMode: (mode: "all" | "selected") => void;
  onToggle: (id: string, allowed: boolean) => void;
  onSave: () => Promise<void> | void;
  onCancel: () => void;
  onReload: () => void;
}
