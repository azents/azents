import type {
  ActionExecutionProjectionResponse,
  ChatEventResponse,
  PendingMailboxEnvelope,
  PendingMailboxItem,
} from "@azents/public-client";

export type PendingMailboxCorrelation = `${string}:${string}`;

export interface PendingMailboxEntry {
  envelope: PendingMailboxEnvelope;
  item: PendingMailboxItem;
  deleting: boolean;
}

export interface PendingMailboxState {
  envelopeOrder: string[];
  envelopesById: Record<string, PendingMailboxEnvelope>;
  entriesByCorrelation: Record<string, PendingMailboxEntry>;
  suppressedMailboxIds: Record<string, true>;
  suppressedCorrelations: Record<string, true>;
}

export type PendingMailboxAction =
  | { type: "BASELINE_REPLACED"; envelopes: PendingMailboxEnvelope[] }
  | { type: "UPSERTED"; envelope: PendingMailboxEnvelope }
  | { type: "REMOVED"; mailboxItemId: string }
  | { type: "DURABLE_PROMOTED"; correlation: PendingMailboxCorrelation }
  | { type: "ACTION_OWNERSHIP_UPDATED"; mailboxItemId: string }
  | { type: "MARK_DELETING"; mailboxItemId: string }
  | { type: "DELETE_FAILED"; mailboxItemId: string }
  | { type: "DELETE_SUCCEEDED"; mailboxItemId: string };

export function pendingMailboxCorrelation(
  mailboxItemId: string,
  itemKey: string,
): PendingMailboxCorrelation {
  return `${mailboxItemId}:${itemKey}`;
}

export function emptyPendingMailboxState(): PendingMailboxState {
  return {
    envelopeOrder: [],
    envelopesById: {},
    entriesByCorrelation: {},
    suppressedMailboxIds: {},
    suppressedCorrelations: {},
  };
}

function itemSuppressed(
  state: PendingMailboxState,
  mailboxItemId: string,
  itemKey: string,
): boolean {
  return (
    state.suppressedMailboxIds[mailboxItemId] === true ||
    state.suppressedCorrelations[
      pendingMailboxCorrelation(mailboxItemId, itemKey)
    ] === true
  );
}

function removeEnvelopeEntries(
  entries: Record<string, PendingMailboxEntry>,
  mailboxItemId: string,
): Record<string, PendingMailboxEntry> {
  return Object.fromEntries(
    Object.entries(entries).filter(
      ([, entry]) => entry.envelope.mailbox_item_id !== mailboxItemId,
    ),
  );
}

function addEnvelope(
  state: PendingMailboxState,
  envelope: PendingMailboxEnvelope,
): PendingMailboxState {
  const mailboxItemId = envelope.mailbox_item_id;
  const existingEnvelope = state.envelopesById[mailboxItemId];
  const envelopeOrder = existingEnvelope
    ? state.envelopeOrder
    : [...state.envelopeOrder, mailboxItemId];
  const entries = removeEnvelopeEntries(
    state.entriesByCorrelation,
    mailboxItemId,
  );
  const deleting = Object.values(state.entriesByCorrelation).some(
    (entry) =>
      entry.envelope.mailbox_item_id === mailboxItemId && entry.deleting,
  );

  for (const item of envelope.items) {
    if (itemSuppressed(state, mailboxItemId, item.item_key)) {
      continue;
    }
    const correlation = pendingMailboxCorrelation(mailboxItemId, item.item_key);
    entries[correlation] = {
      envelope,
      item,
      deleting,
    };
  }

  return {
    ...state,
    envelopeOrder,
    envelopesById: {
      ...state.envelopesById,
      [mailboxItemId]: envelope,
    },
    entriesByCorrelation: entries,
  };
}

function replaceBaseline(
  state: PendingMailboxState,
  envelopes: PendingMailboxEnvelope[],
): PendingMailboxState {
  let next: PendingMailboxState = {
    ...state,
    envelopeOrder: [],
    envelopesById: {},
    entriesByCorrelation: {},
  };
  for (const envelope of envelopes) {
    next = addEnvelope(next, envelope);
  }
  return next;
}

function suppressCorrelation(
  state: PendingMailboxState,
  correlation: PendingMailboxCorrelation,
): PendingMailboxState {
  const [mailboxItemId = "", ...itemKeyParts] = correlation.split(":");
  const itemKey = itemKeyParts.join(":");
  const entries = { ...state.entriesByCorrelation };
  delete entries[correlation];
  return {
    ...state,
    entriesByCorrelation: entries,
    suppressedCorrelations: {
      ...state.suppressedCorrelations,
      [pendingMailboxCorrelation(mailboxItemId, itemKey)]: true,
    },
  };
}

function suppressMailbox(
  state: PendingMailboxState,
  mailboxItemId: string,
): PendingMailboxState {
  return {
    ...state,
    entriesByCorrelation: removeEnvelopeEntries(
      state.entriesByCorrelation,
      mailboxItemId,
    ),
    suppressedMailboxIds: {
      ...state.suppressedMailboxIds,
      [mailboxItemId]: true,
    },
  };
}

export function pendingMailboxReducer(
  state: PendingMailboxState,
  action: PendingMailboxAction,
): PendingMailboxState {
  switch (action.type) {
    case "BASELINE_REPLACED":
      return replaceBaseline(state, action.envelopes);
    case "UPSERTED":
      return addEnvelope(state, action.envelope);
    case "REMOVED":
      return {
        ...state,
        envelopeOrder: state.envelopeOrder.filter(
          (id) => id !== action.mailboxItemId,
        ),
        envelopesById: Object.fromEntries(
          Object.entries(state.envelopesById).filter(
            ([id]) => id !== action.mailboxItemId,
          ),
        ),
        entriesByCorrelation: removeEnvelopeEntries(
          state.entriesByCorrelation,
          action.mailboxItemId,
        ),
      };
    case "DURABLE_PROMOTED":
      return suppressCorrelation(state, action.correlation);
    case "ACTION_OWNERSHIP_UPDATED":
      return suppressMailbox(state, action.mailboxItemId);
    case "MARK_DELETING":
      return {
        ...state,
        entriesByCorrelation: Object.fromEntries(
          Object.entries(state.entriesByCorrelation).map(([key, entry]) => [
            key,
            entry.envelope.mailbox_item_id === action.mailboxItemId
              ? { ...entry, deleting: true }
              : entry,
          ]),
        ),
      };
    case "DELETE_FAILED":
      return {
        ...state,
        entriesByCorrelation: Object.fromEntries(
          Object.entries(state.entriesByCorrelation).map(([key, entry]) => [
            key,
            entry.envelope.mailbox_item_id === action.mailboxItemId
              ? { ...entry, deleting: false }
              : entry,
          ]),
        ),
      };
    case "DELETE_SUCCEEDED":
      return suppressMailbox(
        pendingMailboxReducer(state, {
          type: "REMOVED",
          mailboxItemId: action.mailboxItemId,
        }),
        action.mailboxItemId,
      );
  }
}

export function selectPendingMailboxEntries(
  state: PendingMailboxState,
): PendingMailboxEntry[] {
  return state.envelopeOrder.flatMap((mailboxItemId) => {
    const envelope = state.envelopesById[mailboxItemId];
    if (!envelope) {
      return [];
    }
    return envelope.items.flatMap((item) => {
      const correlation = pendingMailboxCorrelation(
        mailboxItemId,
        item.item_key,
      );
      const entry = state.entriesByCorrelation[correlation];
      return entry ? [entry] : [];
    });
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function durableMailboxCorrelation(
  event: ChatEventResponse,
): PendingMailboxCorrelation | null {
  if (!isRecord(event.payload)) {
    return null;
  }
  const mailboxItemId = event.payload.mailbox_item_id;
  const itemKey = event.payload.mailbox_item_key;
  return typeof mailboxItemId === "string" && typeof itemKey === "string"
    ? pendingMailboxCorrelation(mailboxItemId, itemKey)
    : null;
}

export function actionMailboxItemId(
  actionExecution: ActionExecutionProjectionResponse,
): string {
  return actionExecution.execution.source_mailbox_item_id;
}
