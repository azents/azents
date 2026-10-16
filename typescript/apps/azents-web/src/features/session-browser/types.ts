export interface BrowserTarget {
  task_id: string;
  page_id: string;
  resource_incarnation: string;
}

export interface BrowserViewport {
  width: number;
  height: number;
}

export interface BrowserDialog {
  id: string;
  type: string;
  message: string;
}

export interface BrowserStatus {
  type: "status";
  attachment_id: string;
  target: BrowserTarget;
  state: "connected" | "unavailable" | "closed";
  allow_input: boolean;
  viewport: BrowserViewport;
  navigation_id: string;
  dialog: BrowserDialog | null;
  conflict: boolean;
  opened_target: BrowserTarget | null;
}

export interface BrowserEditable {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  input_mode:
    "text" | "email" | "url" | "tel" | "numeric" | "decimal" | "search";
}

export interface BrowserFrame extends BrowserViewport {
  type: "frame";
  attachment_id: string;
  target: BrowserTarget;
  frame_sequence: number;
  navigation_id: string;
  media_type: "image/jpeg";
  editables: readonly BrowserEditable[];
}

export type BrowserInputReason =
  | "browser_read_only"
  | "browser_field_changed"
  | "browser_field_unsupported"
  | "browser_stale_input"
  | "browser_stale_frame"
  | "browser_stale_target"
  | "browser_stale_generation"
  | "browser_invalid_authority"
  | "browser_invalid_url"
  | "browser_input_conflict"
  | "browser_dialog_pending"
  | "browser_stale_dialog"
  | "browser_resource_exhausted"
  | "browser_unavailable"
  | "browser_deadline"
  | "browser_outcome_unknown";

export interface BrowserInputAck {
  type: "input_ack";
  attachment_id: string;
  sequence: number;
  accepted: boolean;
  reason_code: BrowserInputReason | null;
  outcome: "dispatched" | "rejected" | "outcome_unknown";
}

export interface BrowserFieldAttributes {
  input_type:
    "text" | "password" | "email" | "url" | "tel" | "search" | "textarea";
  input_mode:
    | "none"
    | "text"
    | "email"
    | "url"
    | "tel"
    | "numeric"
    | "decimal"
    | "search"
    | null;
  autocomplete: string;
  autocapitalize:
    "off" | "none" | "on" | "sentences" | "words" | "characters" | null;
  autocorrect: "on" | "off" | null;
  spellcheck: boolean;
  enter_key_hint:
    "enter" | "done" | "go" | "next" | "previous" | "search" | "send" | null;
  max_length: number | null;
  min_length: number | null;
  pattern: string;
  required: boolean;
  multiple: boolean;
  placeholder: string;
  name: string;
}

export interface BrowserFieldValue {
  type: "field_value";
  attachment_id: string;
  sequence: number;
  editable_id: string;
  edit_id: string;
  kind: "text" | "password" | "multiline";
  attributes: BrowserFieldAttributes;
  value: string;
}

export type BrowserFieldResult =
  | { type: "opened"; field: BrowserFieldValue }
  | { type: "completed" }
  | { type: "failed"; reason: BrowserInputReason | null; unknown: boolean };

export type BrowserInputAction =
  | {
      kind: "pointer";
      phase: "move" | "down" | "up" | "cancel";
      x: number;
      y: number;
      button: "left" | "middle" | "right" | null;
    }
  | {
      kind: "wheel";
      x: number;
      y: number;
      delta_x: number;
      delta_y: number;
    }
  | { kind: "key"; phase: "down" | "up"; key: string }
  | { kind: "paste"; editable_id: string; text: string }
  | { kind: "field_open"; editable_id: string }
  | {
      kind: "field_replace";
      editable_id: string;
      edit_id: string;
      text: string;
    }
  | { kind: "field_cancel"; edit_id: string }
  | {
      kind: "composition";
      phase: "start" | "commit" | "cancel";
      text: string | null;
    }
  | { kind: "dialog"; dialog_id: string; accept: boolean; text: string | null }
  | { kind: "navigation"; action: "navigate"; url: string }
  | {
      kind: "navigation";
      action: "back" | "forward" | "reload";
      url: null;
    };

export type BrowserNavigationAction = Extract<
  BrowserInputAction,
  { kind: "navigation" }
>;

export type BrowserDialogAction = Extract<
  BrowserInputAction,
  { kind: "dialog" }
>;
export type BrowserCoordinateAction = Exclude<
  BrowserInputAction,
  BrowserDialogAction
>;

export type BrowserFieldAction = Extract<
  BrowserCoordinateAction,
  { kind: "field_open" | "field_replace" | "field_cancel" }
>;

export type BrowserInput = {
  type: "input";
  attachment_id: string;
  sequence: number;
} & (
  | {
      source: BrowserViewport & {
        frame_sequence: number;
        navigation_id: string;
      };
      action: BrowserCoordinateAction;
    }
  | {
      source: null;
      action: BrowserDialogAction;
    }
);

export interface BrowserPageChoice {
  target: BrowserTarget;
  taskLabel: string;
  title: string;
  url: string;
}

export interface BrowserImage {
  url: string;
  frame: BrowserFrame;
}

export type BrowserViewState =
  | { type: "LOADING" }
  | { type: "UNAVAILABLE"; reason: string }
  | { type: "ERROR" }
  | { type: "ACCESS_CHANGED" }
  | { type: "EMPTY" }
  | {
      type: "READY";
      pages: readonly BrowserPageChoice[];
      selected: BrowserPageChoice;
      connection:
        "connecting" | "connected" | "stale" | "closed" | "unavailable";
      image: BrowserImage | null;
      status: BrowserStatus | null;
      canInput: boolean;
      canClose: boolean;
      dialog: BrowserDialog | null;
      conflict: boolean;
      outcomeUnknown: boolean;
    };
