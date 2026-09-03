export function isTerminalProjectionConnectable(state: string | null): boolean {
  return state === "ready" || state === "active" || state === "ended";
}

export function isTerminalProjectionReconnectable(
  state: string | null,
): boolean {
  return state === "ready" || state === "active";
}

export function shouldRestoreChatForTerminalProjection(
  state: string | null,
): boolean {
  return state !== null && !isTerminalProjectionConnectable(state);
}

export function reconcilePendingTerminalInput(
  pending: ReadonlyMap<number, Uint8Array>,
  nextInputSequence: number,
): {
  nextSequence: number;
  resend: Array<{ sequence: number; data: Uint8Array }>;
} {
  const resend = [...pending.entries()]
    .filter(([sequence]) => sequence >= nextInputSequence)
    .sort(([left], [right]) => left - right)
    .map(([sequence, data]) => ({ sequence, data }));
  let expected = nextInputSequence;
  for (const item of resend) {
    if (item.sequence !== expected) {
      throw new Error("Terminal pending input sequence is not contiguous.");
    }
    expected += 1;
  }
  return { nextSequence: expected, resend };
}

export function classifyTerminalOutputSequence(
  highestScheduledSequence: number,
  sequence: number,
): "duplicate" | "next" {
  if (sequence <= highestScheduledSequence) {
    return "duplicate";
  }
  if (sequence !== highestScheduledSequence + 1) {
    throw new Error("Terminal output sequence gap is not allowed.");
  }
  return "next";
}

export function resolveReplayAcknowledgement({
  replayEnded,
  replayMaximumSequence,
  highestRenderedSequence,
}: {
  replayEnded: boolean;
  replayMaximumSequence: number;
  highestRenderedSequence: number;
}): number | null {
  if (!replayEnded || highestRenderedSequence < replayMaximumSequence) {
    return null;
  }
  return replayMaximumSequence;
}
