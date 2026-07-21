export interface ChatScrollAnchorElement {
  readonly isConnected: boolean;
  getBoundingClientRect(): Pick<DOMRect, "top">;
}

export interface ChatScrollAnchor {
  scrollHeight: number;
  scrollTop: number;
  target: ChatScrollAnchorElement | null;
  targetTop: number | null;
}

export function captureChatScrollAnchor(
  viewport: Pick<HTMLDivElement, "scrollHeight" | "scrollTop">,
  target: ChatScrollAnchorElement | null = null,
): ChatScrollAnchor {
  return {
    scrollHeight: viewport.scrollHeight,
    scrollTop: viewport.scrollTop,
    target,
    targetTop: target?.getBoundingClientRect().top ?? null,
  };
}

export function restorePrependScrollTop(
  anchor: ChatScrollAnchor,
  viewport: Pick<HTMLDivElement, "scrollHeight" | "scrollTop">,
): number {
  if (anchor.target !== null && anchor.target.isConnected) {
    const currentTargetTop = anchor.target.getBoundingClientRect().top;
    if (anchor.targetTop !== null) {
      return viewport.scrollTop + currentTargetTop - anchor.targetTop;
    }
  }
  return anchor.scrollTop + viewport.scrollHeight - anchor.scrollHeight;
}
