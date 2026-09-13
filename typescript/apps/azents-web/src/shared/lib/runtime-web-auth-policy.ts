const chromiumBrand = /"(?:Chromium|Google Chrome)";v="([0-9]+)"/;

export function admittedBrowserProfile(request: Request): string | null {
  const clientHint = request.headers.get("sec-ch-ua");
  const userAgent = request.headers.get("user-agent");
  if (clientHint === null || userAgent === null) {
    return null;
  }
  const clientHintVersion = chromiumBrand.exec(clientHint)?.[1];
  const userAgentVersion = /(?:Chrome|Chromium)\/([0-9]+)/.exec(userAgent)?.[1];
  if (
    clientHintVersion == null ||
    userAgentVersion == null ||
    clientHintVersion !== userAgentVersion
  ) {
    return null;
  }
  return `chromium-${clientHintVersion}`;
}

export function encodeMainBinding(
  initiationId: string,
  secret: string,
): string {
  return `${initiationId}.${secret}`;
}

export function decodeMainBinding(
  value: string,
): { initiationId: string; secret: string } | null {
  const separator = value.indexOf(".");
  if (separator !== 32) {
    return null;
  }
  const initiationId = value.slice(0, separator);
  const secret = value.slice(separator + 1);
  return secret.length >= 32 ? { initiationId, secret } : null;
}
