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
