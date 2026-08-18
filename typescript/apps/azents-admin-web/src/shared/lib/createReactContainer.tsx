import type { ComponentType } from "react";

/**
 * createReactContainer implements the container pattern by separating hooks from components.
 *
 * - Containers focus on state management and side effects
 * - Components focus on pure UI rendering
 * - Hooks can be tested independently to verify logic
 *
 * @param displayName - Display name for the container
 * @param containerHook - Hook that returns the container props
 * @param defaultComponent - Default component
 * @returns Container React component
 */
export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
  defaultComponent: ComponentType<O>,
): ComponentType<I & { component?: ComponentType<O> }>;

/**
 * createReactContainer implements the container pattern by separating hooks from components.
 *
 * @param displayName - Display name for the container
 * @param containerHook - Hook that returns the container props
 * @returns Container React component (requires the component prop)
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
      // This branch is unreachable because of the overloaded function signatures
      return null;
    }
    return <Component {...output} />;
  };
  Container.displayName = displayName;
  return Container;
}
