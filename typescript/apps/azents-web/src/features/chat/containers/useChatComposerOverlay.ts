import { useLayoutEffect, useState } from "react";
import type { RefCallback } from "react";

export interface ChatComposerOverlay {
  composerRef: RefCallback<HTMLDivElement>;
  endSpace: number;
  cardTopInset: number;
  cardBottomInset: number;
}

/** Reserve the floating composer's actual height without tracking the keyboard. */
export function useChatComposerOverlay(): ChatComposerOverlay {
  const [composer, setComposer] = useState<HTMLDivElement | null>(null);
  const [geometry, setGeometry] = useState({
    endSpace: 0,
    cardTopInset: 0,
    cardBottomInset: 0,
  });
  useLayoutEffect(() => {
    if (composer === null) {
      return;
    }
    const card = composer.querySelector("[data-chat-composer-card]");
    if (!(card instanceof HTMLElement)) {
      return;
    }
    const update = (): void => {
      const frame = composer.getBoundingClientRect();
      const input = card.getBoundingClientRect();
      const next = {
        endSpace: frame.height,
        cardTopInset: Math.max(0, frame.bottom - input.top),
        cardBottomInset: Math.max(0, frame.bottom - input.bottom),
      };
      setGeometry((previous) =>
        previous.endSpace === next.endSpace &&
        previous.cardTopInset === next.cardTopInset &&
        previous.cardBottomInset === next.cardBottomInset
          ? previous
          : next,
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(composer);
    observer.observe(card);
    return () => observer.disconnect();
  }, [composer]);
  return { composerRef: setComposer, ...geometry };
}
