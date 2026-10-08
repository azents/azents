export function runtimeWebReturnTarget(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u0020\u007f]/.test(value)
  ) {
    return null;
  }
  return value;
}

export function runtimeWebReturnDestination(
  serviceUrl: string,
  returnTarget: string,
): string {
  const target = runtimeWebReturnTarget(returnTarget);
  if (target === null) {
    throw new Error("Invalid Runtime Web return target.");
  }
  return `${new URL(serviceUrl).origin}${target}`;
}

export function runtimeWebReturnTargetWithFragment(
  returnTarget: string,
  fragment: string,
): string {
  return returnTarget.includes("#")
    ? returnTarget
    : `${returnTarget}${fragment}`;
}

export function runtimeWebLoginNextWithFragment(
  next: string | null,
  fragment: string,
): string | null {
  if (next === null) {
    return next;
  }
  if (!next.startsWith("/") || next.startsWith("//")) {
    return null;
  }
  const url = new URL(next, "https://main.azents.invalid");
  if (url.origin !== "https://main.azents.invalid") {
    return null;
  }
  if (
    fragment === "" ||
    (url.pathname !== "/runtime-web/auth" &&
      url.pathname !== "/runtime-web/activate")
  ) {
    return next;
  }
  const target = runtimeWebReturnTarget(
    url.searchParams.get("return_to") ?? "/",
  );
  if (target === null) {
    return next;
  }
  url.searchParams.set(
    "return_to",
    runtimeWebReturnTargetWithFragment(target, fragment),
  );
  return `${url.pathname}${url.search}${url.hash}`;
}
