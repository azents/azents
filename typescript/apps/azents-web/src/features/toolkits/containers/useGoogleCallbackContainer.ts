"use client";
import { readSessionStorageValue, useSessionStorage } from "@mantine/hooks";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  deserializeGoogleResume,
  GOOGLE_RESUME_KEY,
  googleStateDigest,
  sameGoogleResumeAttempt,
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
  const exchange = trpc.toolkit.google.exchange.useMutation().mutateAsync;
  const cancel = trpc.toolkit.google.cancel.useMutation().mutateAsync;
  const [, saveResume] = useSessionStorage<GoogleResume | null>({
    key: GOOGLE_RESUME_KEY,
    defaultValue: null,
    deserialize: deserializeGoogleResume,
  });
  const [result, setResult] = useState<GoogleCallbackProps>({
    state: { type: "VERIFYING" },
    returnPath: null,
  });
  const startedAttempt = useRef<string | null>(null);
  const operation = useRef(0);
  useEffect(() => {
    const generation = ++operation.current;
    let mounted = true;
    const currentOperation = (): boolean =>
      mounted && generation === operation.current;
    const readContext = (): GoogleResume | null =>
      readSessionStorageValue<GoogleResume | null>({
        key: GOOGLE_RESUME_KEY,
        deserialize: deserializeGoogleResume,
      }) ?? null;
    const owns = (
      context: GoogleResume,
      phase: GoogleResume["phase"],
    ): boolean => {
      const current = readContext();
      return (
        currentOperation() &&
        sameGoogleResumeAttempt(current, context) &&
        current?.phase === phase
      );
    };
    window.history.replaceState(null, "", window.location.pathname);
    async function complete(): Promise<void> {
      if (!currentOperation()) {
        return;
      }
      const context = readContext();
      if (
        context == null ||
        context.phase !== "AUTHORIZING" ||
        state == null ||
        Date.parse(context.expiresAt) <= Date.now()
      ) {
        setResult({
          state: { type: "ERROR", reason: "staleCallback" },
          returnPath: null,
        });
        return;
      }
      const digest = await googleStateDigest(state);
      if (!owns(context, "AUTHORIZING")) {
        return;
      }
      if (digest !== context.stateDigest) {
        setResult({
          state: { type: "ERROR", reason: "staleCallback" },
          returnPath: null,
        });
        return;
      }
      if (startedAttempt.current === context.attemptId) {
        return;
      }
      startedAttempt.current = context.attemptId;
      const scope = { handle: context.handle, agentId: context.agentId };
      if (providerError != null || code == null) {
        try {
          const cancelled = await cancel({
            ...scope,
            attemptId: context.attemptId,
          });
          if (!owns(context, "AUTHORIZING")) {
            return;
          }
          saveResume({
            ...context,
            phase: cancelled.publication == null ? "FAILED" : "UNKNOWN",
          });
          router.replace(context.returnPath);
        } catch {
          if (owns(context, "AUTHORIZING")) {
            setResult({
              state: { type: "ERROR", reason: "cancelFailed" },
              returnPath: context.returnPath,
            });
          }
        }
        return;
      }
      saveResume({ ...context, phase: "VERIFYING" });
      try {
        const review = await exchange({ ...scope, code, state });
        if (!owns(context, "VERIFYING")) {
          return;
        }
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
        if (owns(context, "VERIFYING")) {
          setResult({
            state: { type: "ERROR", reason: "verificationUncertain" },
            returnPath: context.returnPath,
          });
        }
      }
    }
    // Let Strict Mode's probe finish before dispatch; one exact attempt owns the external exchange.
    void Promise.resolve()
      .then(complete)
      .catch(() => {
        if (currentOperation()) {
          setResult({
            state: { type: "ERROR", reason: "verificationFailed" },
            returnPath: null,
          });
        }
      });
    return () => {
      mounted = false;
    };
  }, [cancel, code, exchange, providerError, router, saveResume, state]);
  return result;
}
