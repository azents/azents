"use client";
import { readSessionStorageValue, useSessionStorage } from "@mantine/hooks";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  deserializeGoogleResume,
  GOOGLE_RESUME_KEY,
  googleStateDigest,
} from "@/shared/toolkits/google-resume";
import { trpc } from "@/trpc/client";
import type { GoogleCallbackProps } from "../components/GoogleCallback";
import type { GoogleResume } from "@/shared/toolkits/google-resume";

export interface GoogleCallbackContainerProps {
  code: string | null;
  state: string | null;
  providerError: string | null;
}
export function useGoogleCallbackContainer({
  code,
  state,
  providerError,
}: GoogleCallbackContainerProps): GoogleCallbackProps {
  const router = useRouter();
  const exchange = trpc.toolkit.google.exchange.useMutation();
  const cancel = trpc.toolkit.google.cancel.useMutation();
  const [, saveResume] = useSessionStorage<GoogleResume | null>({
    key: GOOGLE_RESUME_KEY,
    defaultValue: null,
    deserialize: deserializeGoogleResume,
  });
  const [result, setResult] = useState<GoogleCallbackProps>({
    state: { type: "VERIFYING" },
    returnPath: null,
  });
  const started = useRef(false);
  useEffect(() => {
    if (started.current) {
      return;
    }
    started.current = true;
    window.history.replaceState(null, "", window.location.pathname);
    const context = readSessionStorageValue<GoogleResume | null>({
      key: GOOGLE_RESUME_KEY,
      deserialize: deserializeGoogleResume,
    });
    async function complete(): Promise<void> {
      if (
        context == null ||
        context.phase !== "AUTHORIZING" ||
        state == null ||
        Date.parse(context.expiresAt) <= Date.now() ||
        (await googleStateDigest(state)) !== context.stateDigest
      ) {
        setResult({
          state: { type: "ERROR", reason: "staleCallback" },
          returnPath: context?.returnPath ?? null,
        });
        return;
      }
      const scope = { handle: context.handle, agentId: context.agentId };
      if (providerError != null || code == null) {
        try {
          await cancel.mutateAsync({ ...scope, attemptId: context.attemptId });
          saveResume({ ...context, phase: "FAILED" });
          router.replace(context.returnPath);
        } catch {
          setResult({
            state: { type: "ERROR", reason: "cancelFailed" },
            returnPath: context.returnPath,
          });
        }
        return;
      }
      saveResume({ ...context, phase: "VERIFYING" });
      try {
        const review = await exchange.mutateAsync({ ...scope, code, state });
        if (
          review.attempt_id !== context.attemptId ||
          review.reconnect_toolkit_id !== (context.toolkitId ?? null)
        ) {
          setResult({
            state: { type: "ERROR", reason: "staleCallback" },
            returnPath: null,
          });
          return;
        }
        saveResume({ ...context, phase: "REVIEW" });
        router.replace(context.returnPath);
      } catch {
        // The review lookup at the originating surface recovers lost responses without replaying exchange.
        setResult({
          state: { type: "ERROR", reason: "verificationUncertain" },
          returnPath: context.returnPath,
        });
      }
    }
    void complete().catch(() =>
      setResult({
        state: { type: "ERROR", reason: "verificationFailed" },
        returnPath: context?.returnPath ?? null,
      }),
    );
  }, [cancel, code, exchange, providerError, router, saveResume, state]);
  return result;
}
