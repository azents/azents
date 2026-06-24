import inspect
import types
from collections import ChainMap
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    MutableMapping,
)
from contextlib import AsyncExitStack
from typing import (
    Annotated,
    Any,
    Coroutine,
    Generic,
    ParamSpec,
    Protocol,
    TypeVar,
    cast,
    get_args,
    overload,
)

from fastapi import Depends, params
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import (
    _solve_generator,  # pyright: ignore[reportPrivateUsage] - FastAPI 내부 API를 의도적으로 사용 (DI container 구현에 필요)
    get_dependant,
)
from starlette.concurrency import run_in_threadpool

T = TypeVar("T")
P = ParamSpec("P")
R_co = TypeVar("R_co", covariant=True)


class Dependency(Protocol, Generic[P, R_co]):
    def __call__(
        self, *args: P.args, **kwargs: P.kwargs
    ) -> AsyncGenerator[R_co] | Generator[R_co] | Awaitable[R_co] | R_co: ...


DependencyCache = MutableMapping[
    tuple[Callable[..., Any] | None, tuple[str, ...], str],
    Any,
]
DependencyOverrides = MutableMapping[
    Dependency[..., Any],
    Dependency[..., Any],
]


class StrongDependencyOverridesProvider(Protocol):
    dependency_overrides: DependencyOverrides


class FastAPIDependencyOverrideProvider(Protocol):
    dependency_overrides: dict[Callable[..., Any], Callable[..., Any]]


DependencyOverridesProvider = (
    StrongDependencyOverridesProvider | FastAPIDependencyOverrideProvider
)


class Runnable(Protocol):
    async def run(self) -> None: ...


DependencyTask = Callable[..., Coroutine[Any, Any, None]] | Callable[..., Runnable]


async def solve_offline_dependencies(
    *,
    dependant: Dependant,
    stack: AsyncExitStack,
    dependency_overrides_provider: DependencyOverridesProvider | None = None,
    dependency_cache: DependencyCache | None = None,
) -> tuple[dict[str, Any], DependencyCache]:
    values: dict[str, Any] = {}
    dependency_cache = dependency_cache or {}
    sub_dependant: Dependant
    for sub_dependant in dependant.dependencies:
        sub_dependant.call = cast(Callable[..., Any], sub_dependant.call)
        call = sub_dependant.call
        use_sub_dependant = sub_dependant
        if (
            dependency_overrides_provider
            and dependency_overrides_provider.dependency_overrides
        ):
            original_call = sub_dependant.call
            call = dependency_overrides_provider.dependency_overrides.get(
                original_call, original_call
            )
            use_path = sub_dependant.path
            assert use_path is not None
            use_sub_dependant = get_dependant(
                path=use_path,
                call=call,
                name=sub_dependant.name,
            )

        solved_result = await solve_offline_dependencies(
            dependant=use_sub_dependant,
            stack=stack,
            dependency_overrides_provider=dependency_overrides_provider,
            dependency_cache=dependency_cache,
        )
        sub_values, sub_dependency_cache = solved_result
        dependency_cache.update(sub_dependency_cache)
        solved: Any
        if sub_dependant.use_cache and sub_dependant.cache_key in dependency_cache:
            solved = dependency_cache[sub_dependant.cache_key]
        elif (
            use_sub_dependant.is_gen_callable or use_sub_dependant.is_async_gen_callable
        ):
            # FastAPI 내부 _solve_generator는 Generator/AsyncGenerator를
            # 처리하여 값을 반환하지만, 타입 시그니처가 이를 정확히 반영하지 못함.
            solved = await cast(
                Coroutine[Any, Any, Any],
                _solve_generator(
                    dependant=use_sub_dependant, stack=stack, sub_values=sub_values
                ),
            )
        elif use_sub_dependant.is_coroutine_callable:
            # pyright가 Dependency protocol의 union 반환 타입을
            # 런타임 분기(is_coroutine_callable)로 좁히지 못함
            solved = await call(**sub_values)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
        else:
            solved = await run_in_threadpool(call, **sub_values)  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
        if sub_dependant.name is not None:
            values[sub_dependant.name] = solved
        if sub_dependant.cache_key not in dependency_cache:
            dependency_cache[sub_dependant.cache_key] = solved
    return values, dependency_cache


class Container:
    """
    Dependency injection container

    .. code-block:: python

        from azcommon import di

        async with di.Container() as container:
            repo = await container.resolve(repos.WatchtowerRepository)
            watchtower = await repo.get(1)
            print(watchtower.platform_id)

    When the container goes out of context, resources are released.
    You can also manually release resources by calling the `drain()` function.

    """

    def __init__(
        self,
        cache: DependencyCache | None = None,
        dependency_overrides: DependencyOverrides | None = None,
    ) -> None:
        super().__init__()
        self._stack = AsyncExitStack()
        self.cache: DependencyCache = {} if cache is None else cache
        self.dependency_overrides: DependencyOverrides = (
            {} if dependency_overrides is None else dependency_overrides
        )
        self.dependency_overrides[get_container] = lambda: self

    @overload
    async def solve(self, dependency: Callable[..., AsyncGenerator[T]]) -> T: ...

    @overload
    async def solve(self, dependency: Callable[..., Generator[T]]) -> T: ...

    @overload
    async def solve(self, dependency: Callable[..., Awaitable[T]]) -> T: ...

    @overload
    async def solve(self, dependency: Callable[..., T]) -> T: ...

    async def solve(
        self,
        dependency: Dependency[..., T],
    ) -> T:
        """
        Resolves FastAPI dependencies.

        """

        def fake_endpoint(dep: Annotated[T, Depends(dependency)]) -> T:
            return dep

        dependant = get_dependant(path="/", call=fake_endpoint)

        values, cache = await solve_offline_dependencies(
            dependant=dependant,
            stack=self._stack,
            dependency_cache=self.cache,
            dependency_overrides_provider=self,
        )
        self.cache = cache
        return fake_endpoint(**values)

    async def drain(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        tb: types.TracebackType | None = None,
    ) -> None:
        """
        Releases resolved resources.

        The release order is the reverse of the resolution order.

        """
        await self._stack.__aexit__(exc_type, exc, tb)
        self.cache.clear()

    async def __aenter__(self) -> "Container":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        tb: types.TracebackType | None = None,
    ) -> None:
        await self.drain(exc_type, exc, tb)

    def sub(self) -> "Container":
        """
        Creates a sub-container.

        A sub-container shares resources with the parent container but does not affect
        the parent's resources.

        """
        return Container(
            cache=ChainMap({}, self.cache),
            dependency_overrides=ChainMap({}, self.dependency_overrides),
        )

    async def preload(
        self,
        *dependencies: Callable[..., Any],
    ) -> None:
        """
        Pre-resolves dependencies and caches them.

        """
        for dependency in dependencies:
            await self.solve(dependency)

    def copy(self) -> "Container":
        """
        Creates a copy of the container.

        The copy is a new container with the same dependencies and overrides.
        Useful for starting a new context with the same dependencies and overrides.

        """
        return Container(
            dependency_overrides=dict(self.dependency_overrides),
        )

    async def run(
        self,
        func: DependencyTask,
    ) -> None:
        """
        Executes a function or class with dependency injection.

        For coroutine functions: resolves dependencies and executes immediately.
        For classes: instantiates with DI, then calls the `run()` async method.

        Example:

        Coroutine-based tasks:

        .. code-block:: python

            async def some_task(some_object: Annotated[SomeObject, Depends()]) -> None:
                await some_object.method()

            await container.run(some_task)

        Class-based tasks:

        .. code-block:: python

            @dataclasses.dataclass(slots=True)
            class SomeTask:
                some_object: Annotated[SomeObject, Depends()]

                async def run(self) -> None:
                    await self.some_object.method()

            await container.run(SomeTask)

        """
        # Original behavior for coroutine functions
        sig = inspect.signature(func)
        bound = sig.bind_partial()
        bound.apply_defaults()

        # Resolve dependencies for each parameter
        for param_name, param in sig.parameters.items():
            if param_name in bound.arguments:
                continue

            if param.annotation is inspect.Parameter.empty:
                continue

            # Check if this is a Depends-annotated parameter
            if hasattr(param.annotation, "__metadata__"):
                metadata = param.annotation.__metadata__
                for meta in metadata:
                    if isinstance(meta, params.Depends):
                        dependency = meta.dependency
                        if dependency is None:
                            # If dependency is None, use the type annotation
                            # param.annotation is Annotated[T, Depends(...)]
                            # We want T
                            args = get_args(param.annotation)
                            if args:
                                dependency = args[0]

                        if dependency is not None:
                            val = await self.solve(dependency)
                            bound.arguments[param_name] = val
                        break

        result = func(*bound.args, **bound.kwargs)
        if inspect.iscoroutine(result):
            await result
        else:
            await cast(Runnable, result).run()


def get_container() -> Container:
    """
    Dependency for getting the current container.
    """
    raise NotImplementedError(
        "this is a placeholder for the container, you should not call this "
        "function directly"
    )
