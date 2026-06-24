/**
 * tRPC HTTP Handler
 * - tRPC endpoint for Next.js App Router
 */
import { fetchRequestHandler } from "@trpc/server/adapters/fetch";
import { createContext } from "@/trpc/context";
import { appRouter } from "@/trpc/routers/_app";

const handler = (req: Request) =>
  fetchRequestHandler({
    endpoint: "/api/trpc",
    req,
    router: appRouter,
    createContext: ({ resHeaders }) => createContext(resHeaders),
    onError: ({ path, error }: { path?: string; error: Error }) => {
      console.error(`tRPC failed on ${path ?? "<no-path>"}: ${error.message}`);
      if (error.stack) {
        console.error(error.stack);
      }
    },
  });

export { handler as GET, handler as POST };
