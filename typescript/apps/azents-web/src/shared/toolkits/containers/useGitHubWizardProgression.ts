"use client";
import { useReducedMotion } from "@mantine/hooks";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import {
  revealGitHubWizardHeading,
  wizardHeadingId,
} from "../github-wizard-progression";
import type { GitHubWizardStep } from "../github-wizard-progression";
import type { RefObject } from "react";

export interface GitHubWizardProgression {
  rootRef: RefObject<HTMLDivElement | null>;
  advance: (step: GitHubWizardStep) => void;
}
/** The request changes only on an explicit gesture, never on mount, typing, or query refresh. */
export function useGitHubWizardProgression(): GitHubWizardProgression {
  const rootRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const [request, setRequest] = useState<{
    step: GitHubWizardStep;
    sequence: number;
  } | null>(null);
  const lastHandled = useRef(0);
  const advance = useCallback((step: GitHubWizardStep): void => {
    setRequest((previous) => ({
      step,
      sequence: (previous?.sequence ?? 0) + 1,
    }));
  }, []);
  useLayoutEffect(() => {
    if (request == null || request.sequence === lastHandled.current) {
      return;
    }
    const heading = rootRef.current?.querySelector<HTMLElement>(
      `#${wizardHeadingId(request.step)}`,
    );
    if (heading == null) {
      return;
    }
    lastHandled.current = request.sequence;
    revealGitHubWizardHeading(heading, reducedMotion === true);
  }, [reducedMotion, request]);
  return { rootRef, advance };
}
