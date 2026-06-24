import type { ComponentType } from "react";

/**
 * createReactContainer는 hook과 컴포넌트를 분리하여 컨테이너 패턴을 구현합니다.
 *
 * - 컨테이너는 상태 관리와 부수 효과에 집중합니다
 * - 컴포넌트는 순수 UI 렌더링에 집중합니다
 * - hook만 테스트하여 로직을 독립적으로 검증할 수 있습니다
 *
 * @param displayName - 컨테이너의 표시 이름
 * @param containerHook - 컨테이너 props를 반환하는 hook
 * @param defaultComponent - 기본 컴포넌트
 * @returns 컨테이너 React 컴포넌트
 */
export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
  defaultComponent: ComponentType<O>,
): ComponentType<I & { component?: ComponentType<O> }>;

/**
 * createReactContainer는 hook과 컴포넌트를 분리하여 컨테이너 패턴을 구현합니다.
 *
 * @param displayName - 컨테이너의 표시 이름
 * @param containerHook - 컨테이너 props를 반환하는 hook
 * @returns 컨테이너 React 컴포넌트 (component prop 필수)
 */
export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
): ComponentType<I & { component: ComponentType<O> }>;

export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
  defaultComponent?: ComponentType<O>,
) {
  const useContainerHook = containerHook;
  const Container = (props: I & { component?: ComponentType<O> }) => {
    const { component: Component = defaultComponent } = props;
    const output = useContainerHook(props);
    if (typeof Component === "undefined") {
      // 오버로드된 함수 시그니처로 인해 이 분기는 도달 불가능
      return null;
    }
    return <Component {...output} />;
  };
  Container.displayName = displayName;
  return Container;
}
