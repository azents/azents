"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

/**
 * Serializer/deserializer interface for query parameter values
 */
export interface QueryStateSerializer<T> {
  parse: (value: string | null) => T;
  stringify: (value: T) => string | null;
}

/**
 * Built-in serializers for common types
 */
export const serializers = {
  /**
   * String serializer (default)
   */
  string: (defaultValue: string = ""): QueryStateSerializer<string> => ({
    parse: (value) => value ?? defaultValue,
    stringify: (value) => (value === defaultValue ? null : value),
  }),

  /**
   * Nullable string serializer
   */
  stringOrNull: (): QueryStateSerializer<string | null> => ({
    parse: (value) => value,
    stringify: (value) => value,
  }),

  /**
   * Integer serializer
   */
  integer: (defaultValue: number = 0): QueryStateSerializer<number> => ({
    parse: (value) => {
      if (value === null) {
        return defaultValue;
      }
      const parsed = parseInt(value, 10);
      return isNaN(parsed) ? defaultValue : parsed;
    },
    stringify: (value) => (value === defaultValue ? null : String(value)),
  }),

  /**
   * Boolean serializer
   */
  boolean: (defaultValue: boolean = false): QueryStateSerializer<boolean> => ({
    parse: (value) => {
      if (value === null) {
        return defaultValue;
      }
      return value === "true" || value === "1";
    },
    stringify: (value) =>
      value === defaultValue ? null : value ? "true" : "false",
  }),

  /**
   * Literal union type serializer (tabs, enums, and similar values)
   */
  literal: <T extends string>(
    values: readonly T[],
    defaultValue: T,
  ): QueryStateSerializer<T> => ({
    parse: (value) => {
      if (value === null) {
        return defaultValue;
      }
      return values.includes(value as T) ? (value as T) : defaultValue;
    },
    stringify: (value) => (value === defaultValue ? null : value),
  }),
};

export interface UseQueryStateOptions<T> {
  /**
   * Serializer used to convert between strings and values
   */
  serializer: QueryStateSerializer<T>;

  /**
   * Whether to replace the current history entry instead of pushing a new one
   * @default false
   */
  replace?: boolean;

  /**
   * Whether to scroll to the top when the value changes
   * @default false
   */
  scroll?: boolean;
}

/**
 * Hook that manages state for a single query parameter
 */
export function useQueryState<T>(
  key: string,
  options: UseQueryStateOptions<T>,
): [T, (value: T | ((prev: T) => T)) => void] {
  const { serializer, replace = false, scroll = false } = options;
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const value = useMemo(() => {
    const rawValue = searchParams.get(key);
    return serializer.parse(rawValue);
  }, [searchParams, key, serializer]);

  const setValue = useCallback(
    (valueOrUpdater: T | ((prev: T) => T)) => {
      const newValue =
        typeof valueOrUpdater === "function"
          ? (valueOrUpdater as (prev: T) => T)(value)
          : valueOrUpdater;

      const params = new URLSearchParams(searchParams.toString());
      const stringValue = serializer.stringify(newValue);

      if (stringValue === null) {
        params.delete(key);
      } else {
        params.set(key, stringValue);
      }

      const queryString = params.toString();
      const newUrl = queryString ? `${pathname}?${queryString}` : pathname;

      if (replace) {
        router.replace(newUrl, { scroll });
      } else {
        router.push(newUrl, { scroll });
      }
    },
    [searchParams, pathname, router, key, serializer, value, replace, scroll],
  );

  return [value, setValue];
}

/**
 * Utility type that infers the value type from a serializer
 */
type InferSerializerType<S> =
  S extends QueryStateSerializer<infer T> ? T : never;

/**
 * Utility type that infers the state type from a schema
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- any is required for type inference
type InferSchemaState<T extends Record<string, QueryStateSerializer<any>>> = {
  [K in keyof T]: InferSerializerType<T[K]>;
};

/**
 * Hook that manages multiple query parameters at once
 *
 * Using useQueryState multiple times triggers sequential router.push calls,
 * which can overwrite earlier updates.
 * This hook applies all parameters to one URLSearchParams instance
 * and calls router.push or router.replace only once.
 *
 * @example
 * ```tsx
 * const [state, setState] = useQueryStates({
 *   workspaceId: serializers.stringOrNull(),
 *   teamId: serializers.stringOrNull(),
 * });
 *
 * // Update multiple values at once
 * setState({ workspaceId: "ws-123", teamId: null });
 * ```
 */
export function useQueryStates<
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- any is required for type inference
  T extends Record<string, QueryStateSerializer<any>>,
>(
  schema: T,
  options?: { replace?: boolean; scroll?: boolean },
): [InferSchemaState<T>, (updates: Partial<InferSchemaState<T>>) => void] {
  const { replace = false, scroll = false } = options ?? {};
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const state = useMemo(() => {
    const result = {} as InferSchemaState<T>;
    for (const key in schema) {
      const serializer = schema[key];
      if (!serializer) {
        continue;
      }
      const rawValue = searchParams.get(key);
      (result as Record<string, unknown>)[key] = serializer.parse(rawValue);
    }
    return result;
  }, [searchParams, schema]);

  const setState = useCallback(
    (updates: Partial<InferSchemaState<T>>) => {
      const params = new URLSearchParams(searchParams.toString());

      for (const key in updates) {
        const serializer = schema[key];
        if (!serializer) {
          continue;
        }
        const value = updates[key];
        const stringValue = serializer.stringify(value);

        if (stringValue === null) {
          params.delete(key);
        } else {
          params.set(key, stringValue);
        }
      }

      const queryString = params.toString();
      const newUrl = queryString ? `${pathname}?${queryString}` : pathname;

      if (replace) {
        router.replace(newUrl, { scroll });
      } else {
        router.push(newUrl, { scroll });
      }
    },
    [searchParams, pathname, router, schema, replace, scroll],
  );

  return [state, setState];
}
