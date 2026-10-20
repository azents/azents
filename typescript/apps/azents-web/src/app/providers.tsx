"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { TRPCClientError } from "@trpc/client";
import { httpLink } from "@trpc/client";
import { getQueryKey } from "@trpc/react-query";
import { useCallback, useState } from "react";
import superjson from "superjson";
import { trpc } from "@/trpc/client";
import type { AgentListResponse, AgentResponse } from "@azents/public-client";

function isDeletionConflict(error: unknown): boolean {
  if (!(error instanceof TRPCClientError)) {
    return false;
  }
  const data: unknown = error.data;
  if (typeof data !== "object" || data === null || !("apiError" in data)) {
    return false;
  }
  const detail: unknown = data.apiError;
  return (
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    detail.code === "agent_decommissioning"
  );
}

function mutationAgentScope(
  variables: unknown,
): { handle: string; agentId: string } | null {
  if (typeof variables !== "object" || variables === null) {
    return null;
  }
  if (
    "handle" in variables &&
    typeof variables.handle === "string" &&
    "agentId" in variables &&
    typeof variables.agentId === "string"
  ) {
    return { handle: variables.handle, agentId: variables.agentId };
  }
  return null;
}

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

interface TRPCProviderProps {
  children: React.ReactNode;
  redirectOnUnauthorized?: boolean;
}

export function TRPCProvider({
  children,
  redirectOnUnauthorized = true,
}: TRPCProviderProps): React.ReactElement {
  const handleAuthError = useCallback(
    (error: unknown) => {
      if (redirectOnUnauthorized && isUnauthorizedError(error)) {
        redirectToLogin();
      }
    },
    [redirectOnUnauthorized],
  );

  const [queryClient] = useState(() => {
    const client = new QueryClient({
      queryCache: new QueryCache({
        onError: handleAuthError,
      }),
      mutationCache: new MutationCache({
        onError: async (error, variables) => {
          handleAuthError(error);
          if (!isDeletionConflict(error)) {
            return;
          }
          const key = getQueryKey(trpc.agent);
          await client.cancelQueries({ queryKey: key });
          const scope = mutationAgentScope(variables);
          if (scope !== null) {
            client.setQueriesData<AgentResponse>(
              { queryKey: getQueryKey(trpc.agent.get, scope, "query") },
              (agent) =>
                agent
                  ? {
                      ...agent,
                      deletion_status: agent.deletion_status ?? "deleting",
                    }
                  : agent,
            );
            client.setQueriesData<AgentListResponse>(
              {
                queryKey: getQueryKey(
                  trpc.agent.list,
                  { handle: scope.handle },
                  "query",
                ),
              },
              (list) =>
                list
                  ? {
                      ...list,
                      items: list.items.map((agent) =>
                        agent.id === scope.agentId
                          ? {
                              ...agent,
                              deletion_status:
                                agent.deletion_status ?? "deleting",
                            }
                          : agent,
                      ),
                    }
                  : list,
            );
          }
          await client.invalidateQueries({ queryKey: key });
        },
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
    });
    return client;
  });

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
