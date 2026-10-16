import { useLayoutEffect, useState } from "react";

export interface BrowserEditorViewport {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** Track the visible area, not an inferred keyboard height. */
export function useBrowserEditorViewport(
  opened: boolean,
): BrowserEditorViewport | null {
  const [viewport, setViewport] = useState<BrowserEditorViewport | null>(null);
  useLayoutEffect(() => {
    if (!opened) {
      return;
    }
    const visual = window.visualViewport;
    const update = (): void => {
      setViewport({
        top: visual?.offsetTop ?? 0,
        left: visual?.offsetLeft ?? 0,
        width: visual?.width ?? window.innerWidth,
        height: visual?.height ?? window.innerHeight,
      });
    };
    update();
    visual?.addEventListener("resize", update);
    visual?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      visual?.removeEventListener("resize", update);
      visual?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [opened]);
  return opened ? viewport : null;
}
