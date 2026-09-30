/**
 * Forward only the authorized backend capability without following it server-side.
 * The browser owns navigation and GET; issuance does not observe download EOF.
 */
export function browserDownloadRedirect(
  response: Response,
  headers: Headers,
): Response {
  if (response.status !== 302) {
    if (response.ok || response.status < 400) {
      throw new Error("File download did not return an authorized redirect.");
    }
    return Response.json(
      { error: "Failed to prepare file download" },
      { status: response.status, headers },
    );
  }
  const location = response.headers.get("location");
  if (!location) {
    throw new Error("File download redirect is missing.");
  }
  let target: URL;
  try {
    target = new URL(location);
  } catch {
    throw new Error("File download redirect is invalid.");
  }
  if (
    !["https:", "http:"].includes(target.protocol) ||
    target.username ||
    target.password
  ) {
    throw new Error("File download redirect is invalid.");
  }
  headers.set("Location", location);
  headers.set("Cache-Control", "no-store");
  headers.set("Referrer-Policy", "no-referrer");
  return new Response(null, { status: 302, headers });
}
