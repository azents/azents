import "server-only";

/**
 * fetch wrapper that works around body.source loss caused by Next.js fetch patch.
 *
 * ## Background
 *
 * Next.js patches globalThis.fetch for Server Component data caching/revalidation
 * (patch-fetch.ts). When input is a Request object, the patched fetch recreates
 * the Request and passes body as ReadableStream during that process:
 *
 *   // Next.js patch-fetch.ts
 *   if (isRequestInput) {
 *     input = new Request(reqInput.url, { body: reqInput.body, ... });
 *   }
 *
 * A Request body created from a string is internally a ReadableStream, but the
 * original string is preserved in body.source. However, passing this
 * ReadableStream as body of a new Request makes body.source null.
 *
 * ## Problem
 *
 * undici, Node.js built-in HTTP client, runs Fetch spec HTTP authentication
 * retry logic after a 401 response. It needs to resend the request body and
 * therefore references body.source. When source is null, retry is impossible
 * and it returns the "expected non-null body source" network error.
 *
 * Additionally, undici has an unimplemented bug where isTraversableNavigable()
 * always returns true with "// TODO return true", so this authentication retry
 * logic also runs in server environments (it should run only in browsers).
 *
 * As a result, POST/PUT/PATCH requests sent as fetch(Request) through hey-api
 * client fail with TypeError: fetch failed when server returns 401, making normal
 * 401 error handling impossible.
 *
 * ## Solution
 *
 * This wrapper converts fetch(Request) calls into fetch(url, init). Next.js patch
 * recreates only when input is a Request object, so passing URL string preserves
 * body.source by keeping body as the original string.
 *
 * @see https://github.com/vercel/next.js/issues/66840
 */
export const safeFetch: typeof fetch = async (input, init) => {
  if (input instanceof Request && input.body) {
    const body = await input.clone().arrayBuffer();
    return globalThis.fetch(input.url, {
      method: input.method,
      headers: input.headers,
      body,
      redirect: input.redirect,
      signal: input.signal,
      ...init,
    });
  }
  return globalThis.fetch(input, init);
};
