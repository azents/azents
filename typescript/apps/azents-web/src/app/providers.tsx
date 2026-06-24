"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { TRPCClientError } from "@trpc/client";
import { httpLink } from "@trpc/client";
import { useCallback, useState } from "react";
import superjson from "superjson";
import { trpc } from "@/trpc/client";

/** Check whether UNAUTHORIZED error */
function isUnauthorizedError(error: unknown): boolean {
  if (!(error instanceof TRPCClientError)) {
    return false;
  }
  const data: unknown = error.data;
  return (
    typeof data === "object" &&
    data !== null &&
    "code" in data &&
    data.code === "UNAUTHORIZED"
  );
}

/** Redirect to login page on UNAUTHORIZED error */
function redirectToLogin(): void {
  const returnUrl = window.location.pathname + window.location.search;
  window.location.href = `/login?next=${encodeURIComponent(returnUrl)}`;
}

export function TRPCProvider({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  const handleAuthError = useCallback((error: unknown) => {
    if (isUnauthorizedError(error)) {
      redirectToLogin();
    }
  }, []);

  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: handleAuthError,
        }),
        mutationCache: new MutationCache({
          onError: handleAuthError,
        }),
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000, // 5 minutes
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Do not retry UNAUTHORIZED
              if (isUnauthorizedError(error)) {
                return false;
              }
              return failureCount < 3;
            },
          },
          mutations: {
            retry: false,
          },
        },
      }),
  );

  const [trpcClient] = useState(() =>
    trpc.createClient({
      links: [
        httpLink({
          url: "/api/trpc",
          transformer: superjson,
        }),
      ],
    }),
  );

  return (
    <trpc.Provider client={trpcClient} queryClient={queryClient}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </trpc.Provider>
  );
}
