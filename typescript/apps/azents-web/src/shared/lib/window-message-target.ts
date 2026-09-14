interface WindowMessageTarget {
  postMessage(message: unknown, targetOrigin: string): void;
}

export function isWindowMessageTarget(
  value: unknown,
): value is WindowMessageTarget {
  return (
    typeof value === "object" &&
    value !== null &&
    "postMessage" in value &&
    typeof value.postMessage === "function"
  );
}
