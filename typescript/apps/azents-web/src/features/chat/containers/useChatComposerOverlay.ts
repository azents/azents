import { useElementSize } from "@mantine/hooks";
import type { RefCallback } from "react";

export interface ChatComposerOverlay {
  composerRef: RefCallback<HTMLDivElement>;
  endSpace: number;
}

/** Reserve the floating composer's actual height without tracking the keyboard. */
export function useChatComposerOverlay(): ChatComposerOverlay {
  const { ref, height } = useElementSize<HTMLDivElement>();
  return { composerRef: ref, endSpace: height };
}
