"use client";
import { useEffect, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  googleApplicationDirty,
  googleApplicationDraft,
  googleApplicationPatch,
} from "../google-application-state";
import type { GoogleApplicationDraft } from "../google-application-state";
import type { GoogleApplicationDetail } from "@azents/admin-client";

export type GoogleApplicationCardState =
  | { type: "LOADING" }
  | { type: "ERROR"; onReload: () => void }
  | {
      type: "LOADED";
      detail: GoogleApplicationDetail;
      draft: GoogleApplicationDraft;
      dirty: boolean;
      saving: boolean;
      reloadRequired: boolean;
      error: "conflict" | "uncertain" | null;
      onDraftChange: (patch: Partial<GoogleApplicationDraft>) => void;
      onSave: () => void;
      onReload: () => void;
    };
export interface GoogleApplicationCardProps {
  state: GoogleApplicationCardState;
}
export function useGoogleApplicationCardContainer(): GoogleApplicationCardProps {
  const utils = trpc.useUtils();
  const query = trpc.systemSettings.getGoogleApplication.useQuery(void 0, {
    retry: false,
  });
  const [draft, setDraft] = useState<GoogleApplicationDraft | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [error, setError] = useState<"conflict" | "uncertain" | null>(null);
  const [reloadState, setReloadState] = useState<"IDLE" | "PENDING" | "FAILED">(
    "IDLE",
  );
  useEffect(() => {
    if (query.data != null && version == null) {
      setDraft(googleApplicationDraft(query.data));
      setVersion(query.data.admin_version);
    }
  }, [query.data, version]);
  const mutation = trpc.systemSettings.patchGoogleApplication.useMutation({
    onSuccess: async (detail) => {
      setDraft(googleApplicationDraft(detail));
      setVersion(detail.admin_version);
      setError(null);
      await Promise.all([
        utils.systemSettings.getGoogleApplication.invalidate(),
        utils.systemSettings.listAuditEvents.invalidate(),
      ]);
    },
    onError: (failure) => {
      setError(failure.data?.code === "CONFLICT" ? "conflict" : "uncertain");
    },
  });
  const reload = (): void => {
    if (mutation.isPending || reloadState === "PENDING") {
      return;
    }
    setError(null);
    setDraft(null);
    setReloadState("PENDING");
    void utils.systemSettings.getGoogleApplication
      .fetch(void 0, {
        retry: false,
        staleTime: 0,
      })
      .then((detail) => {
        setDraft(googleApplicationDraft(detail));
        setVersion(detail.admin_version);
        setReloadState("IDLE");
      })
      .catch(() => setReloadState("FAILED"));
  };
  if (query.isPending || reloadState === "PENDING") {
    return { state: { type: "LOADING" } };
  }
  if (query.isError || reloadState === "FAILED") {
    return { state: { type: "ERROR", onReload: reload } };
  }
  if (draft == null || version == null) {
    return { state: { type: "LOADING" } };
  }
  const detail = query.data;
  const dirty = googleApplicationDirty(draft);
  const reloadRequired = error != null || detail.admin_version !== version;
  return {
    state: {
      type: "LOADED",
      detail,
      draft,
      dirty,
      saving: mutation.isPending,
      reloadRequired,
      error,
      onDraftChange: (patch) =>
        setDraft((current) =>
          current == null ? current : { ...current, ...patch },
        ),
      onSave: () => {
        if (dirty && !reloadRequired && !mutation.isPending) {
          mutation.mutate(googleApplicationPatch(draft, version));
        }
      },
      onReload: reload,
    },
  };
}
