import classes from "./ScrollContainedViewport.module.css";
import type { ReactElement, ReactNode } from "react";

/** A full-screen workspace whose native scrollers own vertical touch panning. */
export function ScrollContainedViewport({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  return (
    <div className={classes.viewport} data-scroll-contained-viewport>
      {children}
    </div>
  );
}
