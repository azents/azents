"""Request composition retains the application's exact resource bindings."""

from collections.abc import AsyncIterator, Callable
from typing import Annotated

import pytest
from azcommon import di
from fastapi import Depends, FastAPI, Request, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.routing import Mount

from azents.app import (
    create_admin_api_app,
    create_public_api_app,
    create_testenv_api_app,
)
from azents.core.config import Config, Settings
from azents.core.deps import AppContextBinding, get_appctx
from azents.process_lifecycle import create_container
from azents.runtime import deps as runtime_deps
from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_coordination.store import RuntimeTerminalCoordinationStore
from azents.runtime.terminal_dispatcher import RuntimeTerminalControlDispatcherAdapter
from azents.runtime.terminal_integration import (
    CoordinatedRuntimeTerminalInvalidationPublisher,
    RuntimeTerminalPolicyInvalidationPublisher,
)
from azents.services.runtime_terminal.invalidation import (
    NoopRuntimeTerminalInvalidationPublisher,
    RuntimeTerminalInvalidationPublisherDependency,
    get_runtime_terminal_invalidation_publisher,
)
from azents.services.terminal_policy.invalidation import (
    NoopTerminalPolicyInvalidationPublisher,
    TerminalPolicyInvalidationPublisherDependency,
    get_terminal_policy_invalidation_publisher,
)
from azents.utils.appctx import AppContext


@pytest.fixture
def binding_config() -> Config:
    """Build real configuration without opening any external resource."""
    return Config.from_settings(
        Settings(
            _env_file=None,
            rdb_host="unused.invalid",
            rdb_user="bindings-test",
            rdb_db_name="bindings-test",
            auth_jwt_secret_key="bindings-test-secret",
            credential_encryption_key="00" * 32,
            testenv_api_enabled=True,
        )
    )


def _mount_binding_evidence(
    app: FastAPI,
    *,
    expected_context: AppContext[Config],
    expected_container: di.Container,
) -> None:
    """Expose only object identity, not configuration or credential values."""

    @app.get("/binding-evidence")
    def evidence(
        context: Annotated[AppContext[Config], Depends(get_appctx)],
        container: Annotated[di.Container, Depends(di.get_container)],
    ) -> dict[str, bool]:
        return {
            "context": context is expected_context,
            "container": container is expected_container,
        }

    @app.websocket("/binding-evidence-ws")
    async def websocket_evidence(
        websocket: WebSocket,
        context: Annotated[AppContext[Config], Depends(get_appctx)],
        container: Annotated[di.Container, Depends(di.get_container)],
    ) -> None:
        await websocket.accept()
        await websocket.send_json(
            {
                "context": context is expected_context,
                "container": container is expected_container,
            }
        )
        await websocket.close()


@pytest.mark.parametrize(
    "factory",
    [create_public_api_app, create_admin_api_app, create_testenv_api_app],
)
def test_application_bindings_serve_http_and_websocket_without_overrides(
    binding_config: Config,
    factory: Callable[[Config], FastAPI],
) -> None:
    """Fixed production bindings leave FastAPI's dynamic override map empty."""
    app = factory(binding_config)
    binding = app.state.appctx_binding
    container = app.state.di_container
    assert isinstance(binding, AppContextBinding)
    assert isinstance(container, di.Container)
    assert app.dependency_overrides == {}
    _mount_binding_evidence(
        app,
        expected_context=binding.appctx,
        expected_container=container,
    )
    client = TestClient(app)
    try:
        assert client.get("/binding-evidence").json() == {
            "context": True,
            "container": True,
        }
        with client.websocket_connect("/binding-evidence-ws") as websocket:
            assert websocket.receive_json() == {"context": True, "container": True}
    finally:
        client.close()


def test_internal_mount_shares_exact_borrowed_bindings(binding_config: Config) -> None:
    """Mounting the internal API does not create another context or container."""
    context = AppContext(binding_config)
    container = create_container(context)
    app = create_public_api_app(binding_config, appctx=context, container=container)
    internal = next(
        route.app
        for route in app.routes
        if isinstance(route, Mount) and route.path == "/internal"
    )
    assert isinstance(internal, FastAPI)
    assert internal.state.appctx_binding is app.state.appctx_binding
    assert internal.state.di_container is container
    assert internal.dependency_overrides is app.dependency_overrides
    _mount_binding_evidence(
        internal,
        expected_context=context,
        expected_container=container,
    )
    client = TestClient(app)
    try:
        assert client.get("/internal/binding-evidence").json() == {
            "context": True,
            "container": True,
        }
    finally:
        client.close()


@pytest.mark.asyncio
async def test_canonical_context_binding_retains_offline_identity(
    binding_config: Config,
) -> None:
    """Offline resolution returns the exact existing owner without entering it."""
    context = AppContext(binding_config)
    container = create_container(context)
    binding = container.dependency_overrides[get_appctx]
    assert isinstance(binding, AppContextBinding)
    assert binding.appctx is context
    async with container:
        assert await container.solve(get_appctx) is context


def test_context_binding_for_another_owner_remains_an_explicit_override(
    binding_config: Config,
) -> None:
    """Only the binding for the actual app owner leaves the HTTP override map."""
    context = AppContext(binding_config)
    custom_context = AppContext(binding_config)
    container = create_container(context)
    custom_binding = AppContextBinding(custom_context)
    container.dependency_overrides[get_appctx] = custom_binding
    app = create_public_api_app(binding_config, appctx=context, container=container)
    assert app.dependency_overrides[get_appctx] is custom_binding
    _mount_binding_evidence(
        app,
        expected_context=custom_context,
        expected_container=container,
    )
    client = TestClient(app)
    try:
        assert client.get("/binding-evidence").json() == {
            "context": True,
            "container": True,
        }
    finally:
        client.close()


@pytest.mark.parametrize("internal_mount", [False, True])
@pytest.mark.parametrize("generator", [False, True])
def test_custom_context_override_retains_request_injection_and_lifetime(
    binding_config: Config,
    internal_mount: bool,
    generator: bool,
) -> None:
    """Custom context providers resolve per request and clean up after streaming."""
    context = AppContext(binding_config)
    custom_context = AppContext(binding_config)
    container = create_container(context)
    events: list[str] = []

    def request_override(request: Request) -> AppContext[Config]:
        events.append(f"context:request:{request.headers['x-evidence']}")
        return custom_context

    async def generator_override(
        request: Request,
    ) -> AsyncIterator[AppContext[Config]]:
        value = request.headers["x-evidence"]
        events.append(f"context:request:{value}")
        try:
            yield custom_context
        finally:
            events.append(f"context:close:{value}")

    provider = generator_override if generator else request_override
    container.dependency_overrides[get_appctx] = provider
    app = create_public_api_app(binding_config, appctx=context, container=container)
    assert app.dependency_overrides[get_appctx] is provider
    endpoint_app = app
    if internal_mount:
        endpoint_app = next(
            route.app
            for route in app.routes
            if isinstance(route, Mount) and route.path == "/internal"
        )
        assert isinstance(endpoint_app, FastAPI)

    @endpoint_app.get("/context-evidence")
    def evidence(
        request: Request,
        resolved_context: Annotated[AppContext[Config], Depends(get_appctx)],
    ) -> StreamingResponse:
        assert resolved_context is custom_context
        value = request.headers["x-evidence"]
        events.append(f"route:{value}")

        async def body() -> AsyncIterator[str]:
            events.append(f"stream:{value}")
            yield value

        return StreamingResponse(body())

    path = "/context-evidence"
    if internal_mount:
        path = f"/internal{path}"
    client = TestClient(app)
    try:
        for value in ["first", "second"]:
            assert client.get(path, headers={"x-evidence": value}).text == value
            expected = [
                f"context:request:{value}",
                f"route:{value}",
                f"stream:{value}",
            ]
            if generator:
                expected.append(f"context:close:{value}")
            assert events == expected
            events.clear()
    finally:
        client.close()


def test_custom_publishers_and_explicit_overrides_keep_their_identity(
    binding_config: Config,
) -> None:
    """Canonical process bindings and explicitly overridden test dependencies work."""
    context = AppContext(binding_config)
    container = create_container(context)
    runtime_publisher = NoopRuntimeTerminalInvalidationPublisher()
    policy_publisher = NoopTerminalPolicyInvalidationPublisher()
    container.dependency_overrides[get_runtime_terminal_invalidation_publisher] = (
        lambda: runtime_publisher
    )
    container.dependency_overrides[get_terminal_policy_invalidation_publisher] = (
        lambda: policy_publisher
    )

    def marker() -> str:
        return "original"

    container.dependency_overrides[marker] = lambda: "configured"
    app = create_public_api_app(binding_config, appctx=context, container=container)
    assert set(app.dependency_overrides) == {
        marker,
        get_runtime_terminal_invalidation_publisher,
        get_terminal_policy_invalidation_publisher,
    }

    @app.get("/publisher-evidence")
    def evidence(
        runtime: RuntimeTerminalInvalidationPublisherDependency,
        policy: TerminalPolicyInvalidationPublisherDependency,
        value: Annotated[str, Depends(marker)],
    ) -> dict[str, bool | str]:
        return {
            "runtime": runtime is runtime_publisher,
            "policy": policy is policy_publisher,
            "marker": value,
        }

    client = TestClient(app)
    try:
        for _ in range(2):
            assert client.get("/publisher-evidence").json() == {
                "runtime": True,
                "policy": True,
                "marker": "configured",
            }
        app.dependency_overrides[marker] = lambda: "explicit"
        assert client.get("/publisher-evidence").json()["marker"] == "explicit"
        explicit_runtime = NoopRuntimeTerminalInvalidationPublisher()
        explicit_policy = NoopTerminalPolicyInvalidationPublisher()
        app.dependency_overrides.update(
            {
                get_runtime_terminal_invalidation_publisher: lambda: explicit_runtime,
                get_terminal_policy_invalidation_publisher: lambda: explicit_policy,
            }
        )
        overridden = client.get("/publisher-evidence").json()
        assert overridden["runtime"] is False
        assert overridden["policy"] is False
        assert overridden["marker"] == "explicit"
    finally:
        client.close()


@pytest.mark.parametrize("internal_mount", [False, True])
def test_custom_publishers_receive_each_request(
    binding_config: Config,
    internal_mount: bool,
) -> None:
    """Configured custom publishers retain ordinary FastAPI Request injection."""
    context = AppContext(binding_config)
    container = create_container(context)
    requests: list[str] = []
    runtime_publisher = NoopRuntimeTerminalInvalidationPublisher()
    policy_publisher = NoopTerminalPolicyInvalidationPublisher()

    def runtime_override(request: Request) -> NoopRuntimeTerminalInvalidationPublisher:
        requests.append(f"runtime:{request.headers['x-evidence']}")
        return runtime_publisher

    def policy_override(request: Request) -> NoopTerminalPolicyInvalidationPublisher:
        requests.append(f"policy:{request.headers['x-evidence']}")
        return policy_publisher

    container.dependency_overrides[get_runtime_terminal_invalidation_publisher] = (
        runtime_override
    )
    container.dependency_overrides[get_terminal_policy_invalidation_publisher] = (
        policy_override
    )
    app = create_public_api_app(binding_config, appctx=context, container=container)
    endpoint_app = app
    if internal_mount:
        endpoint_app = next(
            route.app
            for route in app.routes
            if isinstance(route, Mount) and route.path == "/internal"
        )
        assert isinstance(endpoint_app, FastAPI)

    @endpoint_app.get("/request-publisher-evidence")
    def evidence(
        runtime: RuntimeTerminalInvalidationPublisherDependency,
        policy: TerminalPolicyInvalidationPublisherDependency,
    ) -> dict[str, bool]:
        return {
            "runtime": runtime is runtime_publisher,
            "policy": policy is policy_publisher,
        }

    path = "/request-publisher-evidence"
    if internal_mount:
        path = f"/internal{path}"
    client = TestClient(app)
    try:
        for value in ["first", "second"]:
            assert client.get(path, headers={"x-evidence": value}).json() == {
                "runtime": True,
                "policy": True,
            }
        assert requests == [
            "runtime:first",
            "policy:first",
            "runtime:second",
            "policy:second",
        ]
    finally:
        client.close()


@pytest.mark.parametrize("internal_mount", [False, True])
def test_custom_publisher_generators_close_after_each_streaming_response(
    binding_config: Config,
    internal_mount: bool,
) -> None:
    """Custom generator publishers close at request exit, not container shutdown."""
    context = AppContext(binding_config)
    container = create_container(context)
    events: list[str] = []
    runtime_publisher = NoopRuntimeTerminalInvalidationPublisher()
    policy_publisher = NoopTerminalPolicyInvalidationPublisher()

    async def runtime_override(
        request: Request,
    ) -> AsyncIterator[NoopRuntimeTerminalInvalidationPublisher]:
        value = request.headers["x-evidence"]
        events.append(f"runtime:open:{value}")
        try:
            yield runtime_publisher
        finally:
            events.append(f"runtime:close:{value}")

    async def policy_override(
        request: Request,
    ) -> AsyncIterator[NoopTerminalPolicyInvalidationPublisher]:
        value = request.headers["x-evidence"]
        events.append(f"policy:open:{value}")
        try:
            yield policy_publisher
        finally:
            events.append(f"policy:close:{value}")

    container.dependency_overrides[get_runtime_terminal_invalidation_publisher] = (
        runtime_override
    )
    container.dependency_overrides[get_terminal_policy_invalidation_publisher] = (
        policy_override
    )
    app = create_public_api_app(binding_config, appctx=context, container=container)
    endpoint_app = app
    if internal_mount:
        endpoint_app = next(
            route.app
            for route in app.routes
            if isinstance(route, Mount) and route.path == "/internal"
        )
        assert isinstance(endpoint_app, FastAPI)

    @endpoint_app.get("/generator-publisher-evidence")
    def evidence(
        request: Request,
        runtime: RuntimeTerminalInvalidationPublisherDependency,
        policy: TerminalPolicyInvalidationPublisherDependency,
    ) -> StreamingResponse:
        assert runtime is runtime_publisher
        assert policy is policy_publisher
        value = request.headers["x-evidence"]
        events.append(f"route:{value}")

        async def body() -> AsyncIterator[str]:
            events.append(f"stream:{value}")
            yield value

        return StreamingResponse(body())

    path = "/generator-publisher-evidence"
    if internal_mount:
        path = f"/internal{path}"
    client = TestClient(app)
    try:
        for value in ["first", "second"]:
            assert client.get(path, headers={"x-evidence": value}).text == value
            assert events == [
                f"runtime:open:{value}",
                f"policy:open:{value}",
                f"route:{value}",
                f"stream:{value}",
                f"policy:close:{value}",
                f"runtime:close:{value}",
            ]
            events.clear()
    finally:
        client.close()


def _mount_canonical_publisher_evidence(
    app: FastAPI,
    *,
    expected_store: RuntimeTerminalCoordinationStore,
    expected_dispatcher: RuntimeTerminalControlDispatcherAdapter | None,
    events: list[str],
) -> None:
    """Verify concrete publishers use the same request-composed collaborators."""

    @app.get("/canonical-publisher-evidence")
    async def evidence(
        request: Request,
        runtime: RuntimeTerminalInvalidationPublisherDependency,
        policy: TerminalPolicyInvalidationPublisherDependency,
        store: Annotated[
            RuntimeTerminalCoordinationStore,
            Depends(runtime_deps.get_runtime_terminal_coordination_store),
        ],
        dispatcher: Annotated[
            RuntimeTerminalControlDispatcherAdapter,
            Depends(runtime_deps.get_runtime_terminal_control_dispatcher),
        ],
    ) -> StreamingResponse:
        assert isinstance(runtime, CoordinatedRuntimeTerminalInvalidationPublisher)
        assert isinstance(policy, RuntimeTerminalPolicyInvalidationPublisher)
        assert runtime._store is policy._store is store is expected_store
        assert runtime._dispatcher is policy._dispatcher is dispatcher
        if expected_dispatcher is not None:
            assert dispatcher is expected_dispatcher
        value = request.headers["x-evidence"]
        events.append(f"route:{value}")

        async def body() -> AsyncIterator[str]:
            events.append(f"stream:{value}")
            yield value

        return StreamingResponse(body())


def _publisher_endpoint_app(app: FastAPI, *, internal_mount: bool) -> FastAPI:
    """Select the existing parent or internal app without creating another owner."""
    if not internal_mount:
        return app
    internal = next(
        route.app
        for route in app.routes
        if isinstance(route, Mount) and route.path == "/internal"
    )
    assert isinstance(internal, FastAPI)
    return internal


@pytest.mark.asyncio
async def test_offline_publishers_retain_canonical_container_composition(
    binding_config: Config,
) -> None:
    """Non-HTTP ports keep their configured providers and shared collaborators."""
    context = AppContext(binding_config)
    container = create_container(context)
    store = InMemoryRuntimeTerminalCoordinationStore()
    runtime_store = InMemoryRuntimeCoordinationStore()
    dispatcher = RuntimeTerminalControlDispatcherAdapter(
        control_protocol=RuntimeControlProtocolService(runtime_store),
        terminal_coordination=store,
        runtime_coordination=runtime_store,
    )
    assert (
        container.dependency_overrides[get_runtime_terminal_invalidation_publisher]
        is runtime_deps.get_runtime_terminal_invalidation_publisher
    )
    assert (
        container.dependency_overrides[get_terminal_policy_invalidation_publisher]
        is runtime_deps.get_runtime_terminal_policy_invalidation_publisher
    )
    container.dependency_overrides.update(
        {
            runtime_deps.get_runtime_terminal_coordination_store: lambda: store,
            runtime_deps.get_runtime_terminal_control_dispatcher: lambda: dispatcher,
        }
    )
    async with container:
        runtime = await container.solve(get_runtime_terminal_invalidation_publisher)
        policy = await container.solve(get_terminal_policy_invalidation_publisher)
        assert isinstance(runtime, CoordinatedRuntimeTerminalInvalidationPublisher)
        assert isinstance(policy, RuntimeTerminalPolicyInvalidationPublisher)
        assert runtime._store is policy._store is store
        assert runtime._dispatcher is policy._dispatcher is dispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize("internal_mount", [False, True])
@pytest.mark.parametrize("generator", [False, True])
async def test_canonical_publishers_use_custom_request_context(
    binding_config: Config,
    internal_mount: bool,
    generator: bool,
) -> None:
    """Default publisher/store composition supports custom request-scoped contexts."""
    context = AppContext(binding_config)
    custom_context = AppContext(binding_config)
    container = create_container(context)
    store = InMemoryRuntimeTerminalCoordinationStore()
    runtime_store = InMemoryRuntimeCoordinationStore()
    events: list[str] = []

    async def terminal_store_factory() -> AsyncIterator[
        RuntimeTerminalCoordinationStore
    ]:
        yield store

    async def runtime_store_factory() -> AsyncIterator[RuntimeCoordinationStore]:
        yield runtime_store

    def request_override(request: Request) -> AppContext[Config]:
        events.append(f"context:request:{request.headers['x-evidence']}")
        return custom_context

    async def generator_override(
        request: Request,
    ) -> AsyncIterator[AppContext[Config]]:
        value = request.headers["x-evidence"]
        events.append(f"context:request:{value}")
        try:
            yield custom_context
        finally:
            events.append(f"context:close:{value}")

    provider = generator_override if generator else request_override
    container.dependency_overrides[get_appctx] = provider
    app = create_public_api_app(binding_config, appctx=context, container=container)
    assert set(app.dependency_overrides) == {get_appctx}
    _mount_canonical_publisher_evidence(
        _publisher_endpoint_app(app, internal_mount=internal_mount),
        expected_store=store,
        expected_dispatcher=None,
        events=events,
    )
    path = "/canonical-publisher-evidence"
    if internal_mount:
        path = f"/internal{path}"
    async with custom_context, container:
        await custom_context.get_variable(
            f"{runtime_deps.__name__}.get_runtime_terminal_coordination_store",
            terminal_store_factory,
        )
        await custom_context.get_variable(
            f"{runtime_deps.__name__}.get_runtime_coordination_store",
            runtime_store_factory,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://bindings.test",
        ) as client:
            for value in ["first", "second"]:
                response = await client.get(path, headers={"x-evidence": value})
                assert response.text == value
                expected = [
                    f"context:request:{value}",
                    f"route:{value}",
                    f"stream:{value}",
                ]
                if generator:
                    expected.append(f"context:close:{value}")
                assert events == expected
                events.clear()


@pytest.mark.parametrize("internal_mount", [False, True])
@pytest.mark.parametrize("generator", [False, True])
def test_canonical_publishers_use_explicit_request_store_and_dispatcher_overrides(
    binding_config: Config,
    internal_mount: bool,
    generator: bool,
) -> None:
    """App-level collaborator overrides remain inside normal FastAPI composition."""
    context = AppContext(binding_config)
    container = create_container(context)
    store = InMemoryRuntimeTerminalCoordinationStore()
    runtime_store = InMemoryRuntimeCoordinationStore()
    dispatcher = RuntimeTerminalControlDispatcherAdapter(
        control_protocol=RuntimeControlProtocolService(runtime_store),
        terminal_coordination=store,
        runtime_coordination=runtime_store,
    )
    events: list[str] = []

    def store_override(request: Request) -> RuntimeTerminalCoordinationStore:
        events.append(f"store:request:{request.headers['x-evidence']}")
        return store

    async def store_generator(
        request: Request,
    ) -> AsyncIterator[RuntimeTerminalCoordinationStore]:
        value = request.headers["x-evidence"]
        events.append(f"store:request:{value}")
        try:
            yield store
        finally:
            events.append(f"store:close:{value}")

    def dispatcher_override(
        request: Request,
    ) -> RuntimeTerminalControlDispatcherAdapter:
        events.append(f"dispatcher:request:{request.headers['x-evidence']}")
        return dispatcher

    async def dispatcher_generator(
        request: Request,
    ) -> AsyncIterator[RuntimeTerminalControlDispatcherAdapter]:
        value = request.headers["x-evidence"]
        events.append(f"dispatcher:request:{value}")
        try:
            yield dispatcher
        finally:
            events.append(f"dispatcher:close:{value}")

    app = create_public_api_app(binding_config, appctx=context, container=container)
    assert app.dependency_overrides == {}
    app.dependency_overrides.update(
        {
            runtime_deps.get_runtime_terminal_coordination_store: (
                store_generator if generator else store_override
            ),
            runtime_deps.get_runtime_terminal_control_dispatcher: (
                dispatcher_generator if generator else dispatcher_override
            ),
        }
    )
    _mount_canonical_publisher_evidence(
        _publisher_endpoint_app(app, internal_mount=internal_mount),
        expected_store=store,
        expected_dispatcher=dispatcher,
        events=events,
    )
    path = "/canonical-publisher-evidence"
    if internal_mount:
        path = f"/internal{path}"
    client = TestClient(app)
    try:
        for value in ["first", "second"]:
            assert client.get(path, headers={"x-evidence": value}).text == value
            expected = [
                f"store:request:{value}",
                f"dispatcher:request:{value}",
                f"route:{value}",
                f"stream:{value}",
            ]
            if generator:
                expected.extend(
                    [
                        f"dispatcher:close:{value}",
                        f"store:close:{value}",
                    ]
                )
            assert events == expected
            events.clear()
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("recursive", [False, True])
async def test_unconfigured_publishers_fail_without_recursion(recursive: bool) -> None:
    """A missing or recursive application binding never degrades to a no-op."""
    container = di.Container()
    if recursive:
        container.dependency_overrides[get_runtime_terminal_invalidation_publisher] = (
            get_runtime_terminal_invalidation_publisher
        )
        container.dependency_overrides[get_terminal_policy_invalidation_publisher] = (
            get_terminal_policy_invalidation_publisher
        )
    with pytest.raises(RuntimeError, match="Runtime Terminal invalidation binding"):
        await get_runtime_terminal_invalidation_publisher(
            container,
            NoopRuntimeTerminalInvalidationPublisher(),
        )
    with pytest.raises(RuntimeError, match="Terminal policy invalidation binding"):
        await get_terminal_policy_invalidation_publisher(
            container,
            NoopTerminalPolicyInvalidationPublisher(),
        )
