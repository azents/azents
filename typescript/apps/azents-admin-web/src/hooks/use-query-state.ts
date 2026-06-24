"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

/**
 * 쿼리 파라미터 값을 위한 Serializer/Deserializer 인터페이스
 */
export interface QueryStateSerializer<T> {
  parse: (value: string | null) => T;
  stringify: (value: T) => string | null;
}

/**
 * 일반적인 타입을 위한 내장 serializer
 */
export const serializers = {
  /**
   * String serializer (기본값)
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
   * Literal union type serializer (탭, enum 등)
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
   * 문자열과 값 사이를 변환하는 데 사용할 serializer
   */
  serializer: QueryStateSerializer<T>;

  /**
   * push 대신 현재 history 항목을 replace할지 여부
   * @default false
   */
  replace?: boolean;

  /**
   * 값이 변경될 때 상단으로 스크롤할지 여부
   * @default false
   */
  scroll?: boolean;
}

/**
 * 단일 쿼리 파라미터 상태를 관리하는 Hook
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
 * Serializer에서 값 타입을 추론하는 유틸리티 타입
 */
type InferSerializerType<S> =
  S extends QueryStateSerializer<infer T> ? T : never;

/**
 * Schema에서 상태 타입을 추론하는 유틸리티 타입
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- 타입 추론을 위해 any 사용 필요
type InferSchemaState<T extends Record<string, QueryStateSerializer<any>>> = {
  [K in keyof T]: InferSerializerType<T[K]>;
};

/**
 * 여러 쿼리 파라미터를 한번에 관리하는 Hook
 *
 * 개별 useQueryState를 여러 번 사용하면 순차적 router.push 호출로
 * 이전 업데이트가 덮어씌워지는 문제가 발생합니다.
 * 이 Hook은 모든 파라미터를 하나의 URLSearchParams에 반영한 뒤
 * 단 한 번의 router.push/replace를 호출합니다.
 *
 * @example
 * ```tsx
 * const [state, setState] = useQueryStates({
 *   workspaceId: serializers.stringOrNull(),
 *   teamId: serializers.stringOrNull(),
 * });
 *
 * // 여러 값을 동시에 업데이트
 * setState({ workspaceId: "ws-123", teamId: null });
 * ```
 */
export function useQueryStates<
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 타입 추론을 위해 any 사용 필요
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
