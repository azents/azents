"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { httpLink } from "@trpc/client";
import { useState } from "react";
import superjson from "superjson";
import { useConfig } from "@/config/client";
import { getPublicRouteUrl } from "@/shared/lib/auth-policy";
import { trpc } from "@/trpc/client";

export function TRPCProvider({ children }: { children: React.ReactNode }) {
  const config = useConfig();

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000, // 5분
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  const [trpcClient] = useState(() =>
    trpc.createClient({
      links: [
        httpLink({
          url: getPublicRouteUrl(config.publicBaseUrl, "/api/trpc"),
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
