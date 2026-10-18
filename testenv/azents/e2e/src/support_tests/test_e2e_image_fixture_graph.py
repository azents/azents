"""Exercise real image readiness/owner fixtures with Docker-free dependencies."""

import inspect
import json
import threading
from collections.abc import Callable, Generator
from os import PathLike
from typing import Self
from unittest.mock import Mock

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from support.e2e_image_preparation import E2EImagePreparation
from tests import conftest as e2e_conftest

pytest_plugins = ["pytester"]


class FakeContainer(DockerContainer):
    """Implement only construction/start/stop used by prerequisite ownership."""

    def __init__(self, name: str, events: list[str], failure: str) -> None:
        self.name = name
        self.events = events
        self.failure = failure
        self.started = False

    def with_network(self, network: Network) -> Self:
        return self

    def with_network_aliases(self, *aliases: str) -> Self:
        return self

    def with_env(self, key: str, value: str) -> Self:
        return self

    def with_command(self, command: str | list[str]) -> Self:
        return self

    def with_exposed_ports(self, *ports: str | int) -> Self:
        return self

    def with_volume_mapping(
        self, host: str | PathLike[str], container: str, mode: str = "ro"
    ) -> Self:
        return self

    def start(self) -> Self:
        if self.failure == "infra_failure" and self.name == "postgres":
            raise LookupError("infrastructure failure")
        self.started = True
        self.events.append(f"start:{self.name}")
        return self

    def stop(self, force: bool = True, delete_volume: bool = True) -> None:
        if self.started:
            self.events.append(f"stop:{self.name}")
            if self.failure == "cleanup_failure" and self.name == "postgres":
                raise ValueError("cleanup failure")


class FixtureGraph:
    """Register actual fixture units while replacing external dependencies."""

    def __init__(
        self,
        preparation: E2EImagePreparation,
        release_web: threading.Event,
        events: list[str],
        failure: str,
    ) -> None:
        self.preparation = preparation
        self.release_web = release_web
        self.events = events
        self.failure = failure
        self.reports: list[pytest.TestReport] = []

    @pytest.fixture(scope="session")
    def container_network(self) -> None:
        return None

    @pytest.fixture(scope="session")
    def azents_runtime_provider_docker_container(
        self,
        server_e2e_images: dict[str, str],
        azents_runtime_runner_image: str,
        azents_runtime_provider_docker_image: str,
    ) -> Generator[DockerContainer, None, None]:
        assert set(server_e2e_images) == {"azents-server"}
        assert azents_runtime_runner_image == "current-azents-runtime-runner"
        assert azents_runtime_provider_docker_image == (
            "current-azents-runtime-provider-docker"
        )
        assert not self.preparation.futures["azents-web"].done()
        self.events.append("backend-ready")
        self.release_web.set()
        if self.failure == "provider_failure":
            raise LookupError("backend setup failure")
        yield FakeContainer("provider", self.events, self.failure)
        self.events.append("provider-finalized")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports.append(report)


@pytest.mark.parametrize(
    ("failure", "passed", "errors"),
    [
        ("success", 1, 0),
        ("web_failure", 0, 1),
        ("admin_failure", 0, 1),
        ("provider_failure", 0, 2),
        ("infra_failure", 0, 1),
        ("cleanup_failure", 1, 1),
    ],
)
def test_actual_fixture_graph_orders_backend_before_full_join_and_drains(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    passed: int,
    errors: int,
) -> None:
    release_web = threading.Event()
    events: list[str] = []
    supplied = {
        image.cache_repository: f"current-{image.cache_repository}"
        for image in e2e_conftest._CORE_E2E_IMAGE_BUILDS
    }

    def web() -> str:
        if failure == "infra_failure":
            release_web.set()
        assert release_web.wait(5)
        events.append("web-build-finished")
        if failure in {"web_failure", "provider_failure", "infra_failure"}:
            raise ValueError("Web build failure")
        return "current-web"

    def admin_web() -> str:
        if failure == "admin_failure":
            raise ValueError("Admin Web build failure")
        return "current-admin-web"

    preparation = E2EImagePreparation(
        supplied,
        {"azents-web": web, "azents-admin-web": admin_web},
    )
    plugin = FixtureGraph(preparation, release_web, events, failure)
    constructors = 0

    def container(*args: object, **kwargs: object) -> FakeContainer:
        nonlocal constructors
        constructors += 1
        return FakeContainer(f"infra-{constructors}", events, failure)

    monkeypatch.setattr(e2e_conftest, "DockerContainer", container)
    monkeypatch.setattr(
        e2e_conftest,
        "PostgresContainer",
        lambda *args, **kwargs: FakeContainer("postgres", events, failure),
    )
    monkeypatch.setattr(e2e_conftest, "_initialize_testcontainers_reaper", lambda: None)
    monkeypatch.setattr(e2e_conftest, "_wait_for_fixture_health", Mock())
    monkeypatch.setattr(
        e2e_conftest, "_e2e_image_preparation", lambda profile: preparation
    )
    artifact_root = pytester.path / "artifacts"
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(artifact_root))
    # Import real fixture units into the nested test's module-level conftest.
    # Pytest's plugin scanner intentionally ignores instance-only definitions.
    pytester.makeconftest(
        "from tests.conftest import core_prerequisites, server_e2e_images, "
        "azents_runtime_runner_image, azents_runtime_provider_docker_image, "
        "e2e_images, s3_credentials\n"
        "from tests.web.conftest import web_suite_substrate\n"
    )
    pytester.makepyfile("def test_web_consumer(e2e_images):\n    assert e2e_images\n")
    result = pytester.runpytest_inprocess(
        "-q",
        "-p",
        "no:cacheprovider",
        f"--confcutdir={pytester.path}",
        plugins=[plugin],
    )
    result.assert_outcomes(passed=passed, errors=errors)
    call_reports = [report for report in plugin.reports if report.when == "call"]
    assert len(call_reports) == passed
    assert preparation.closed
    assert all(
        future.done() and not future.cancelled()
        for future in preparation.futures.values()
    )
    if failure != "infra_failure":
        assert events.index("backend-ready") < events.index("web-build-finished")
    tracked_stops = [
        index for index, event in enumerate(events) if event.startswith("stop:")
    ]
    assert tracked_stops
    assert events.index("web-build-finished") < min(tracked_stops)
    timing_report = json.loads(
        (artifact_root / "core-prerequisite-timings.json").read_text()
    )
    assert timing_report["readiness_scope"] == (
        "infrastructure" if failure == "infra_failure" else "server"
    )
    if failure == "infra_failure":
        assert not timing_report["completed"]
        assert (
            "server_image_ready_at_monotonic" not in timing_report["readiness_timings"]
        )
    assert "e2e_images" not in timing_report["tasks"]
    readiness = timing_report["readiness_timings"]
    assert "image_owner_drained_at_monotonic" in readiness
    if failure != "infra_failure":
        assert timing_report["completed"]
        assert (
            readiness["core_prerequisites_ready_at_monotonic"]
            <= readiness["image_owner_drained_at_monotonic"]
        )
    if failure in {"success", "cleanup_failure"}:
        assert (
            readiness["core_prerequisites_ready_at_monotonic"]
            <= readiness["backend_ready_at_monotonic"]
            <= readiness["full_images_ready_at_monotonic"]
            <= readiness["image_owner_drained_at_monotonic"]
        )
    if failure in {"web_failure", "admin_failure"}:
        assert "full_images_join_failed_at_monotonic" in readiness
        assert "full_images_ready_at_monotonic" not in readiness
    if failure == "provider_failure":
        assert any(
            report.when == "setup" and report.failed for report in plugin.reports
        )
        assert any(
            report.when == "teardown" and report.failed for report in plugin.reports
        )
        assert "backend setup failure" in str(
            next(report.longrepr for report in plugin.reports if report.when == "setup")
        )
        assert "ImagePreparationError" in str(
            next(
                report.longrepr
                for report in plugin.reports
                if report.when == "teardown"
            )
        )


def test_backend_dependency_closure_never_reaches_full_image_view() -> None:
    def dependencies(name: str) -> set[str]:
        fixture = getattr(e2e_conftest, name, None)
        if fixture is None:
            return set()
        return set(inspect.signature(fixture).parameters)

    visited: set[str] = set()
    pending = ["azents_runtime_provider_docker_container"]
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        pending.extend(dependencies(name))
    assert "e2e_images" not in visited
    assert "azents_web_image" not in visited
    assert "azents_admin_web_image" not in visited
    assert {
        "azents_core_service_containers",
        "azents_database_schema",
        "azents_workspace_upload_gateway_container",
        "azents_runtime_control_container",
        "system_bootstrap_evidence",
        "runtime_provider_credential",
        "server_e2e_images",
    } <= visited
    assert "azents_runtime_provider_docker_container" in dependencies("e2e_images")


class BrowserFreeGraph(FixtureGraph):
    """Keep an unused Web image blocked until a real browser-free test body."""

    @pytest.fixture(scope="session")
    def azents_runtime_provider_docker_container(
        self,
        server_e2e_images: dict[str, str],
        azents_runtime_runner_image: str,
        azents_runtime_provider_docker_image: str,
    ) -> Generator[DockerContainer, None, None]:
        assert set(server_e2e_images) == {"azents-server"}
        assert azents_runtime_runner_image == "current-azents-runtime-runner"
        assert azents_runtime_provider_docker_image == (
            "current-azents-runtime-provider-docker"
        )
        self.events.append("backend-ready")
        yield FakeContainer("provider", self.events, self.failure)
        self.events.append("provider-finalized")

    @pytest.fixture
    def release_unused_image(self) -> Callable[[], None]:
        def release() -> None:
            assert not self.preparation.futures["azents-web"].done()
            self.events.append("browser-free-body")
            self.release_web.set()

        return release


@pytest.mark.parametrize("failure", ["success", "web_failure", "admin_failure"])
def test_browser_free_body_overlaps_images_without_dropping_failure_ownership(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    release_web = threading.Event()
    events: list[str] = []
    supplied = {
        image.cache_repository: f"current-{image.cache_repository}"
        for image in e2e_conftest._CORE_E2E_IMAGE_BUILDS
    }

    def web() -> str:
        assert release_web.wait(5)
        events.append("web-build-finished")
        if failure == "web_failure":
            raise ValueError("Web build failure")
        return "current-web"

    def admin() -> str:
        if failure == "admin_failure":
            raise ValueError("Admin Web build failure")
        return "current-admin"

    preparation = E2EImagePreparation(
        supplied, {"azents-web": web, "azents-admin-web": admin}
    )
    plugin = BrowserFreeGraph(preparation, release_web, events, failure)
    monkeypatch.setattr(
        e2e_conftest,
        "DockerContainer",
        lambda *args, **kwargs: FakeContainer("infra", events, failure),
    )
    monkeypatch.setattr(
        e2e_conftest,
        "PostgresContainer",
        lambda *args, **kwargs: FakeContainer("postgres", events, failure),
    )
    monkeypatch.setattr(e2e_conftest, "_initialize_testcontainers_reaper", lambda: None)
    monkeypatch.setattr(e2e_conftest, "_wait_for_fixture_health", Mock())
    monkeypatch.setattr(
        e2e_conftest, "_e2e_image_preparation", lambda profile: preparation
    )
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(pytester.path / "artifacts"))
    pytester.makeconftest(
        "from tests.conftest import core_prerequisites, server_e2e_images, "
        "azents_runtime_runner_image, azents_runtime_provider_docker_image, "
        "s3_credentials\n"
        "from tests.web.conftest import web_suite_substrate\n"
    )
    pytester.makepyfile(
        "def test_browser_free_body(release_unused_image):\n"
        "    release_unused_image()\n"
    )
    result = pytester.runpytest_inprocess(
        "-q",
        "-p",
        "no:cacheprovider",
        f"--confcutdir={pytester.path}",
        plugins=[plugin],
    )
    result.assert_outcomes(passed=1, errors=0 if failure == "success" else 1)
    assert preparation.closed
    assert all(
        future.done() and not future.cancelled()
        for future in preparation.futures.values()
    )
    assert events.index("backend-ready") < events.index("browser-free-body")
    assert events.index("browser-free-body") < events.index("web-build-finished")
    assert events.index("web-build-finished") < min(
        index for index, event in enumerate(events) if event.startswith("stop:")
    )
    assert (
        len(
            [
                report
                for report in plugin.reports
                if report.when == "call" and report.passed
            ]
        )
        == 1
    )
    if failure != "success":
        assert any(
            report.when == "teardown" and report.failed for report in plugin.reports
        )


class ServerFirstGraph(FixtureGraph):
    """Release an independent Runtime build only after a real Server consumer."""

    @pytest.fixture(scope="session")
    def server_consumer(self, azents_server_image: str) -> str:
        assert azents_server_image == "current-azents-server"
        assert not self.preparation.futures["azents-runtime-runner"].done()
        self.events.append("server-consumer-ready")
        self.release_web.set()
        return azents_server_image

    @pytest.fixture(scope="session")
    def runtime_consumer(
        self, server_consumer: str, request: pytest.FixtureRequest
    ) -> str:
        assert server_consumer == "current-azents-server"
        return request.getfixturevalue("azents_runtime_runner_image")


@pytest.mark.parametrize(
    ("fails", "consumed", "passed", "errors"),
    [(False, True, 1, 0), (True, True, 0, 1), (True, False, 1, 1)],
)
def test_server_consumer_precedes_unrelated_runtime_join_without_rebuild(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
    consumed: bool,
    passed: int,
    errors: int,
) -> None:
    release_runtime = threading.Event()
    events: list[str] = []

    def runner() -> str:
        assert release_runtime.wait(5)
        events.append("runtime-build-finished")
        if fails:
            raise LookupError("Runtime build failure")
        return "current-azents-runtime-runner"

    preparation = E2EImagePreparation(
        {
            image.cache_repository: f"current-{image.cache_repository}"
            for image in e2e_conftest._E2E_IMAGE_BUILD_PROFILES["web"]
            if image.cache_repository != "azents-runtime-runner"
        },
        {"azents-runtime-runner": runner},
    )
    plugin = ServerFirstGraph(preparation, release_runtime, events, "success")
    monkeypatch.setattr(
        e2e_conftest,
        "DockerContainer",
        lambda *args, **kwargs: FakeContainer("infra", events, "success"),
    )
    monkeypatch.setattr(
        e2e_conftest,
        "PostgresContainer",
        lambda *args, **kwargs: FakeContainer("postgres", events, "success"),
    )
    monkeypatch.setattr(e2e_conftest, "_initialize_testcontainers_reaper", lambda: None)
    monkeypatch.setattr(e2e_conftest, "_wait_for_fixture_health", Mock())
    monkeypatch.setattr(
        e2e_conftest, "_e2e_image_preparation", lambda profile: preparation
    )
    builder = Mock(side_effect=AssertionError("Image must join its submitted build"))
    monkeypatch.setattr(e2e_conftest, "_build_configured_e2e_image", builder)
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(pytester.path / "artifacts"))
    pytester.makeconftest(
        "from tests.conftest import core_prerequisites, server_e2e_images, "
        "azents_server_image, azents_runtime_runner_image, s3_credentials\n"
    )
    consumer = "runtime_consumer" if consumed else "server_consumer"
    pytester.makepyfile(
        f"def test_actual_consumer({consumer}):\n    assert {consumer}\n"
    )
    result = pytester.runpytest_inprocess(
        "-q",
        "-p",
        "no:cacheprovider",
        f"--confcutdir={pytester.path}",
        plugins=[plugin],
    )
    result.assert_outcomes(passed=passed, errors=errors)
    builder.assert_not_called()
    assert preparation.closed
    assert events.index("server-consumer-ready") < events.index(
        "runtime-build-finished"
    )


class LocalProfileGraph(FixtureGraph):
    """Observe infrastructure-only receipts before the default lazy image build."""

    @pytest.fixture(scope="session")
    def local_server(
        self, server_e2e_images: dict[str, str], request: pytest.FixtureRequest
    ) -> str:
        assert server_e2e_images == {}
        root = request.config.rootpath / "artifacts"
        receipt = json.loads((root / "core-prerequisite-timings.json").read_text())
        assert receipt["completed"]
        assert receipt["readiness_scope"] == "infrastructure"
        assert "server_image_ready_at_monotonic" not in receipt["readiness_timings"]
        return request.getfixturevalue("azents_server_image")


@pytest.mark.parametrize("mode", ["infrastructure", "server", "server_failure"])
def test_default_profile_receipt_never_claims_an_unbuilt_server_ready(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    events: list[str] = []
    preparation = E2EImagePreparation({}, {})
    plugin = LocalProfileGraph(preparation, threading.Event(), events, "success")
    monkeypatch.delenv("AZENTS_E2E_SERVER_IMAGE", raising=False)
    monkeypatch.setattr(
        e2e_conftest,
        "DockerContainer",
        lambda *args, **kwargs: FakeContainer("infra", events, "success"),
    )
    monkeypatch.setattr(
        e2e_conftest,
        "PostgresContainer",
        lambda *args, **kwargs: FakeContainer("postgres", events, "success"),
    )
    monkeypatch.setattr(e2e_conftest, "_initialize_testcontainers_reaper", lambda: None)
    monkeypatch.setattr(e2e_conftest, "_wait_for_fixture_health", Mock())
    monkeypatch.setattr(
        e2e_conftest, "_e2e_image_preparation", lambda profile: preparation
    )
    builder = Mock(
        side_effect=LookupError("Lazy Server build failure")
        if mode == "server_failure"
        else None
    )
    monkeypatch.setattr(e2e_conftest, "_build_configured_e2e_image", builder)
    root = pytester.path / "artifacts"
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(root))
    pytester.makeconftest(
        "from tests.conftest import core_prerequisites, server_e2e_images, "
        "azents_server_image, s3_credentials\n"
    )
    consumer = "server_e2e_images" if mode == "infrastructure" else "local_server"
    pytester.makepyfile(
        f"def test_default_path({consumer}):\n    assert {consumer} is not None\n"
    )
    result = pytester.runpytest_inprocess(
        "-q",
        "-p",
        "no:cacheprovider",
        f"--confcutdir={pytester.path}",
        plugins=[plugin],
    )
    result.assert_outcomes(
        passed=0 if mode == "server_failure" else 1,
        errors=1 if mode == "server_failure" else 0,
    )
    receipt = json.loads((root / "core-prerequisite-timings.json").read_text())
    expected_scope = "server" if mode == "server" else "infrastructure"
    assert receipt["readiness_scope"] == expected_scope
    assert ("server_image_ready_at_monotonic" in receipt["readiness_timings"]) == (
        mode == "server"
    )
    if mode == "infrastructure":
        builder.assert_not_called()
    else:
        builder.assert_called_once()
