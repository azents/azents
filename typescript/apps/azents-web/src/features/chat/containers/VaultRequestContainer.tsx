"use client";

import { useSearchParams } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  VaultRequestCard,
  VaultRequestDialog,
} from "../components/VaultRequestView";
import type { VaultRequestView } from "@azents/public-client";
import type { UseQueryResult } from "@tanstack/react-query";
import type { FormEvent, ReactElement, ReactNode } from "react";

interface Scope {
  handle: string;
  agentId: string;
  sessionId: string;
}

const VaultRequestContext = createContext<{
  scope: Scope;
  open: (requestId: string) => void;
} | null>(null);

function useRequest(
  scope: Scope,
  requestId: string,
): Pick<
  UseQueryResult<VaultRequestView>,
  "data" | "isError" | "isPending" | "isFetchedAfterMount"
> {
  return trpc.agent.readVaultRequest.useQuery(
    { ...scope, requestId },
    {
      retry: false,
      refetchOnMount: "always",
      refetchOnReconnect: "always",
      refetchOnWindowFocus: true,
      refetchInterval: (query) => {
        const request = query.state.data;
        if (request?.status !== "open") {
          return false;
        }
        const remaining = Date.parse(request.deadline_at) - Date.now();
        return Math.min(15_000, Math.max(1_000, remaining));
      },
    },
  );
}

export function VaultRequestProvider({
  scope,
  agentName,
  children,
}: {
  scope: Scope;
  agentName: string;
  children: ReactNode;
}): ReactElement {
  const [requestId, setRequestId] = useState<string | null>(null);
  const params = useSearchParams();
  const intent = params.get("vaultRequest");
  const handled = useRef<string | null>(null);
  useEffect(() => {
    if (intent === null) {
      handled.current = null;
      return;
    }
    if (intent === handled.current) {
      return;
    }
    handled.current = intent;
    if (/^[0-9a-f]{32}$/.test(intent)) {
      setRequestId(intent);
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("vaultRequest");
    window.history.replaceState(null, "", url);
  }, [intent]);
  return (
    <VaultRequestContext value={{ scope, open: setRequestId }}>
      {children}
      {requestId !== null && (
        <VaultRequestDialogContainer
          key={requestId}
          scope={scope}
          requestId={requestId}
          agentName={agentName}
          onClose={() => setRequestId(null)}
        />
      )}
    </VaultRequestContext>
  );
}

export function VaultRequestCardContainer({
  requestId,
  snapshot,
}: {
  requestId: string;
  snapshot: VaultRequestView | null;
}): ReactElement | null {
  const context = useContext(VaultRequestContext);
  return context === null ? null : (
    <ConnectedVaultRequestCard
      requestId={requestId}
      snapshot={snapshot}
      scope={context.scope}
      onOpen={() => context.open(requestId)}
    />
  );
}

function ConnectedVaultRequestCard({
  scope,
  requestId,
  snapshot,
  onOpen,
}: {
  scope: Scope;
  requestId: string;
  snapshot: VaultRequestView | null;
  onOpen: () => void;
}): ReactElement {
  const query = useRequest(scope, requestId);
  return (
    <VaultRequestCard
      request={query.isError ? null : (query.data ?? snapshot ?? null)}
      loading={query.isPending}
      onOpen={onOpen}
    />
  );
}

function VaultRequestDialogContainer({
  scope,
  requestId,
  agentName,
  onClose,
}: {
  scope: Scope;
  requestId: string;
  agentName: string;
  onClose: () => void;
}): ReactElement {
  const query = useRequest(scope, requestId);
  const utils = trpc.useUtils();
  const [values, setValues] = useState<ReadonlyMap<string, string>>(
    () => new Map(),
  );
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const submitting = useRef(false);
  // Cached status is useful on a card, but never authorizes opening an input form.
  const request =
    query.isError || !query.isFetchedAfterMount ? null : (query.data ?? null);

  useEffect(() => {
    if (!request?.can_submit) {
      setValues(new Map());
    }
  }, [request?.can_submit]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (submitting.current || request === null || !request.can_submit) {
      return;
    }
    const submission = request.fields.map(({ name }) => ({
      name,
      value: values.get(name) ?? "",
    }));
    if (submission.some(({ value }) => value.length === 0)) {
      return;
    }
    submitting.current = true;
    setBusy(true);
    setFailed(false);
    setValues(new Map());
    // Call the client directly so values never become React Query mutation state.
    void utils.client.agent.submitVaultRequest
      .mutate({ ...scope, requestId, values: submission })
      .then(() => onClose())
      .catch(() => setFailed(true))
      .finally(() => {
        submitting.current = false;
        setBusy(false);
        void utils.agent.readVaultRequest.invalidate({ ...scope, requestId });
      });
  }

  return (
    <VaultRequestDialog
      agentName={agentName}
      request={request}
      loading={!query.isFetchedAfterMount || query.isPending}
      values={values}
      busy={busy}
      failed={failed}
      onClose={onClose}
      onFieldChange={(name, value) =>
        setValues((current) => new Map(current).set(name, value))
      }
      onSubmit={submit}
    />
  );
}
