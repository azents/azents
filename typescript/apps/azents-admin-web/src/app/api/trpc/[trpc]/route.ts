import { fetchRequestHandler } from "@trpc/server/adapters/fetch";
import { hasExpectedOrigin } from "@/shared/lib/same-origin";
import { createContext } from "@/trpc/context";
import { appRouter } from "@/trpc/routers/_app";

function handler(request: Request): Promise<Response> {
  if (request.method === "POST" && !hasExpectedOrigin(request)) {
    return Promise.resolve(
      new Response("A same-origin request is required.", { status: 403 }),
    );
  }

  return fetchRequestHandler({
    endpoint: "/api/trpc",
    req: request,
    router: appRouter,
    createContext: ({ resHeaders }) => createContext(resHeaders),
    onError: ({ path, error }: { path?: string; error: Error }) => {
      console.error(`tRPC failed on ${path ?? "<no-path>"}: ${error.message}`);
    },
  });
}

export { handler as GET, handler as POST };
