export interface ChatScrollAnchor {
  scrollHeight: number;
  scrollTop: number;
}

export function captureChatScrollAnchor(
  viewport: Pick<HTMLDivElement, "scrollHeight" | "scrollTop">,
): ChatScrollAnchor {
  return {
    scrollHeight: viewport.scrollHeight,
    scrollTop: viewport.scrollTop,
  };
}

export function restorePrependScrollTop(
  anchor: ChatScrollAnchor,
  nextScrollHeight: number,
): number {
  return anchor.scrollTop + nextScrollHeight - anchor.scrollHeight;
}
