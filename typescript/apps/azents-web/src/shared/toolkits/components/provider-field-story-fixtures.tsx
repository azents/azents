import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TRPCClientError } from "@trpc/client";
import { observable } from "@trpc/server/observable";
import { useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { TestConnectionResponse } from "@azents/public-client";
import type { ReactElement, ReactNode } from "react";

/** A per-story transport fake: no HTTP link, listener, or live provider request. */
export function ProviderFieldStoryTransport({
  children,
  response,
  onRequest,
  errorMessage = null,
}: {
  children: ReactNode;
  response: TestConnectionResponse;
  onRequest: (input: unknown) => void;
  errorMessage?: string | null;
}): ReactElement {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          mutations: { retry: false },
          queries: { retry: false },
        },
      }),
  );
  const client = useMemo(
    () =>
      trpc.createClient({
        links: [
          () =>
            ({ op }) =>
              observable((observer) => {
                if (op.path !== "toolkit.testConnection") {
                  observer.error(
                    new TRPCClientError("Unknown static fixture operation."),
                  );
                  return;
                }
                onRequest(op.input);
                if (errorMessage !== null) {
                  observer.error(new TRPCClientError(errorMessage));
                  return;
                }
                observer.next({ result: { data: response } });
                observer.complete();
              }),
        ],
      }),
    [errorMessage, onRequest, response],
  );
  return (
    <trpc.Provider client={client} queryClient={queryClient}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </trpc.Provider>
  );
}
