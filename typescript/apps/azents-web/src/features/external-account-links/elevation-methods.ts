import type { AuthMethod } from "@azents/public-client";

const EMPTY_ELEVATION_METHODS: AuthMethod[] = [];

export function elevationMethodsOrEmpty(
  methods?: AuthMethod[] | null,
): AuthMethod[] {
  return methods ?? EMPTY_ELEVATION_METHODS;
}
