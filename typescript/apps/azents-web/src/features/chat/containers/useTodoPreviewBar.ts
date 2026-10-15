"use client";

import { useState } from "react";
import type {
  GoalStateSnapshot,
  TodoStateSnapshot,
} from "@azents/session-core/types";
import type { Dispatch, SetStateAction } from "react";

export interface TodoPreviewBarProps {
  goal: GoalStateSnapshot | null;
  isMobile: boolean;
  todo: TodoStateSnapshot;
  onClearGoal?: () => Promise<boolean>;
  onUpdateGoal?: (objective: string) => Promise<boolean>;
  onPauseGoal?: () => Promise<boolean>;
  onResumeGoal?: (hint?: string) => Promise<boolean>;
}
export type GoalSectionProps = Omit<
  TodoPreviewBarProps,
  "goal" | "isMobile" | "todo"
> & { goal: GoalStateSnapshot };
export interface GoalSectionViewProps extends GoalSectionProps {
  editing: boolean;
  draft: string;
  submitting: boolean;
  confirmAction: "delete" | "pause" | "resume" | null;
  resumeHint: string;
  setEditing: Dispatch<SetStateAction<boolean>>;
  setDraft: Dispatch<SetStateAction<string>>;
  setConfirmAction: Dispatch<
    SetStateAction<"delete" | "pause" | "resume" | null>
  >;
  setResumeHint: Dispatch<SetStateAction<string>>;
  saveGoal: () => void;
  closeConfirm: () => void;
  confirmGoalAction: () => void;
}
export function useGoalSection(props: GoalSectionProps): GoalSectionViewProps {
  const { goal, onClearGoal, onUpdateGoal, onPauseGoal, onResumeGoal } = props;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(goal.objective ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [confirmAction, setConfirmAction] = useState<
    "delete" | "pause" | "resume" | null
  >(null);
  const [resumeHint, setResumeHint] = useState("");
  const saveGoal = (): void => {
    const nextObjective = draft.trim();
    if (!onUpdateGoal || nextObjective === "") {
      return;
    }
    setSubmitting(true);
    void onUpdateGoal(nextObjective).then((ok) => {
      setSubmitting(false);
      if (ok) {
        setEditing(false);
      }
    });
  };
  const closeConfirm = (): void => {
    setConfirmAction(null);
    setResumeHint("");
  };
  const clearGoal = (): void => {
    if (!onClearGoal) {
      return;
    }
    setSubmitting(true);
    void onClearGoal()
      .then((ok) => {
        if (ok) {
          closeConfirm();
        }
      })
      .finally(() => setSubmitting(false));
  };
  const confirmGoalAction = (): void => {
    const action = confirmAction;
    if (action === "delete") {
      clearGoal();
      return;
    }
    if (action === "pause") {
      if (!onPauseGoal) {
        return;
      }
      setSubmitting(true);
      void onPauseGoal().then((ok) => {
        setSubmitting(false);
        if (ok) {
          closeConfirm();
        }
      });
      return;
    }
    if (action === "resume") {
      if (!onResumeGoal) {
        return;
      }
      setSubmitting(true);
      void onResumeGoal(resumeHint).then((ok) => {
        setSubmitting(false);
        if (ok) {
          closeConfirm();
        }
      });
    }
  };
  return {
    ...props,
    editing,
    draft,
    submitting,
    confirmAction,
    resumeHint,
    setEditing,
    setDraft,
    setConfirmAction,
    setResumeHint,
    saveGoal,
    closeConfirm,
    confirmGoalAction,
  };
}
export interface TodoPreviewBarViewProps extends TodoPreviewBarProps {
  opened: boolean;
  setOpened: Dispatch<SetStateAction<boolean>>;
  expandedItems: Set<string>;
  toggleExpanded: (key: string) => void;
}
export function useTodoPreviewBar(
  props: TodoPreviewBarProps,
): TodoPreviewBarViewProps {
  const [opened, setOpened] = useState(false);
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  const toggleExpanded = (key: string): void => {
    setExpandedItems((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };
  return { ...props, opened, setOpened, expandedItems, toggleExpanded };
}
