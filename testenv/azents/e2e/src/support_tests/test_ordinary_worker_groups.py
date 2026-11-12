"""Docker-free checks of the actual bounded ordinary Worker owners."""

import inspect
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from unittest.mock import Mock

import pytest
from testcontainers.core.container import DockerContainer

from tests import conftest as fixtures

pytest_plugins = ["pytester"]


@pytest.mark.parametrize(
    "failure", ["none", "enter", "readiness", "body", "exit", "body_exit"]
)
def test_lazy_worker_owner_restores_original_on_every_exit(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    events: list[str] = []
    original = Mock(spec=DockerContainer)
    wrapped = Mock()
    original.get_wrapped_container.return_value = wrapped
    wrapped.stop.side_effect = lambda **kwargs: events.append("original-stop")
    wrapped.start.side_effect = lambda: events.append("original-start")
    replacement = Mock(spec=DockerContainer)
    replacement.with_env.return_value = replacement
    replacement.__enter__ = Mock(return_value=replacement)
    if failure == "enter":
        replacement.__enter__.side_effect = ValueError("replacement start failed")

    def exit_replacement(*args: object) -> None:
        events.append("replacement-exit")
        if failure in {"exit", "body_exit"}:
            raise ValueError("replacement stop failed")

    replacement.__exit__ = Mock(side_effect=exit_replacement)
    monkeypatch.setattr(
        fixtures, "_create_engine_worker_container", lambda **kwargs: replacement
    )
    monkeypatch.setattr(
        fixtures,
        "_register_server_log_capture",
        lambda *args: events.append("register"),
    )
    monkeypatch.setattr(
        fixtures,
        "_unregister_server_log_capture",
        lambda *args: events.append("unregister"),
    )

    def ready(container: DockerContainer) -> None:
        events.append(
            "original-ready" if container is original else "replacement-ready"
        )
        if failure == "readiness" and container is replacement:
            raise ValueError("replacement readiness failed")

    monkeypatch.setattr(fixtures, "_wait_for_engine_worker_ready", ready)
    factory = inspect.unwrap(fixtures.ordinary_model_stream_worker_factory)(
        original,
        Mock(),
        Mock(),
        "access",
        "secret",
        "bucket",
        "image",
        "jwt",
        "key",
        "bootstrap",
    )
    assert events == []
    try:
        with factory() as observed:
            assert observed is replacement
            events.append("body")
            if failure in {"body", "body_exit"}:
                raise ValueError("case failed")
    except ValueError as error:
        assert failure != "none"
        if failure == "body_exit":
            assert isinstance(error.__context__, ValueError)
            assert str(error.__context__) == "case failed"
    assert events[0] == "original-stop"
    assert events[-3:] == ["original-start", "register", "original-ready"]
    if failure != "enter":
        assert events.index("replacement-exit") < events.index("original-start")
    replacement.with_env.assert_any_call("AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS", "30")
    wrapped.stop.assert_called_once_with(timeout=10)


class GroupOwner:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.worker = Mock(spec=DockerContainer)

    @pytest.fixture(scope="session")
    def ordinary_model_stream_worker_factory(
        self,
    ) -> Callable[[], AbstractContextManager[DockerContainer]]:
        @contextmanager
        def start() -> Generator[DockerContainer, None, None]:
            self.events.append("start")
            try:
                yield self.worker
            finally:
                self.events.append("restore")

        return start

    @pytest.fixture
    def owner(self) -> "GroupOwner":
        return self


@pytest.mark.parametrize("failure", ["none", "body", "drain", "both", "missing"])
def test_actual_group_scope_drains_each_case_and_fails_closed(
    pytester: pytest.Pytester, failure: str
) -> None:
    owner = GroupOwner()
    pytester.makeconftest(
        "from tests.conftest import (\n"
        "    ordinary_model_stream_worker_group, ordinary_model_stream_case,\n"
        ")\n"
    )
    pytester.makepyfile(
        f"""import pytest
class TestPair:
    def test_first(
        self, request, owner,
        ordinary_model_stream_worker_group, ordinary_model_stream_case
    ):
        assert ordinary_model_stream_worker_group is owner.worker
        request.addfinalizer(lambda: owner.events.append("case-finalizer"))
        def drain():
            owner.events.append("drain-first")
            if {failure!r} in ("drain", "both"):
                raise ValueError("drain failed")
        if {failure!r} != "missing":
            ordinary_model_stream_case(drain)
            ordinary_model_stream_case(lambda: owner.events.append("drain-last"))
        owner.events.append("first")
        if {failure!r} in ("body", "both"):
            raise ValueError("primary failure")
    def test_second(
        self, owner, ordinary_model_stream_worker_group, ordinary_model_stream_case
    ):
        assert owner.events == [
            "start", "first", "case-finalizer", "drain-first", "drain-last"
        ]
        assert ordinary_model_stream_worker_group is owner.worker
        ordinary_model_stream_case(lambda: owner.events.append("drain-second"))
        owner.events.append("second")
def test_original_policy_boundary(owner):
    assert owner.events[-1] == "restore"
    owner.events.append("outside")
"""
    )
    result = pytester.runpytest_inprocess(
        "-q", "-p", "no:cacheprovider", f"--confcutdir={pytester.path}", plugins=[owner]
    )
    if failure == "none":
        result.assert_outcomes(passed=3)
    elif failure == "body":
        result.assert_outcomes(passed=2, failed=1)
    else:
        assert result.ret != 0
        assert "second" not in owner.events and "outside" not in owner.events
        expected = "registered no drain" if failure == "missing" else "drain failed"
        assert expected in result.stdout.str()
        if failure == "both":
            result.assert_outcomes(failed=1, errors=1)
            assert "primary failure" in result.stdout.str()
    assert owner.events.count("start") == 1
    assert owner.events.count("restore") == 1
    if failure != "missing":
        assert (
            owner.events.index("case-finalizer")
            < owner.events.index("drain-first")
            < owner.events.index("drain-last")
            < owner.events.index("restore")
        )
