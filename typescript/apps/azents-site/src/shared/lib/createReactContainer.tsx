import type { ComponentType } from "react";

export function createReactContainer<I, O extends object>(
  displayName: string,
  containerHook: (props: I) => O,
  defaultComponent: ComponentType<O>,
): ComponentType<I & { component?: ComponentType<O> }> {
  const Container = (
    props: I & { component?: ComponentType<O> },
  ): React.ReactElement => {
    const { component: Component = defaultComponent } = props;
    const output = containerHook(props);
    return <Component {...output} />;
  };
  Container.displayName = displayName;
  return Container;
}
