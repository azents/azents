import type { ComponentType } from "react";

/**
 * createReactContainer implements the container pattern by separating hook and component.
 *
 * - Container focuses on state management and side effects.
 * - Component focuses on pure UI rendering.
 * - Logic can be verified independently by testing only the hook.
 *
 * @param displayName - Container display name
 * @param containerHook - Hook returning container props
 * @param defaultComponent - Default component
 * @returns Container React component
 */
export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
  defaultComponent: ComponentType<O>,
): ComponentType<I & { component?: ComponentType<O> }>;

/**
 * createReactContainer implements the container pattern by separating hook and component.
 *
 * @param displayName - Container display name
 * @param containerHook - Hook returning container props
 * @returns Container React component (component prop required)
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
      // This branch is unreachable due to overloaded function signatures
      return null;
    }
    return <Component {...output} />;
  };
  Container.displayName = displayName;
  return Container;
}
