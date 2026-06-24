/**
 * tRPC HTTP Handler
 * - Next.js App Router용 tRPC 엔드포인트
 */
import { fetchRequestHandler } from "@trpc/server/adapters/fetch";
import { createContext } from "@/trpc/context";
import { appRouter } from "@/trpc/routers/_app";

const handler = (req: Request) =>
  fetchRequestHandler({
    endpoint: "/api/trpc",
    req,
    router: appRouter,
    createContext,
    onError: ({ path, error }: { path?: string; error: Error }) => {
      console.error(
        `❌ tRPC failed on ${path ?? "<no-path>"}: ${error.message}`,
      );
      if (error.stack) {
        console.error(error.stack);
      }
    },
  });

export { handler as GET, handler as POST };
