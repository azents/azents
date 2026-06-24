"""``testenv`` CLI entrypoint for fixtures and prerequisites."""

import json
import logging
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated

import typer

from .bootstrap_runner import BootstrapLocalResult, run_bootstrap_local
from .fixture_errors import FixtureError
from .fixture_resources import FixtureCommandResult
from .fixture_runner import (
    UnknownFixtureError,
    run_fixture_doctor,
    run_fixture_doctor_all,
    run_fixture_reset,
    run_fixture_up,
)
from .prerequisite_errors import PrerequisiteError
from .prerequisite_prepare import (
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_PREREQUISITE_PROFILE,
    PrerequisitePrepareResult,
    prepare_prerequisite_snapshot,
)

app = typer.Typer(
    name="testenv",
    help="azents testenv — fixture and prerequisite tools.",
    no_args_is_help=True,
)
fixture_app = typer.Typer(
    help="Long-lived fixture lifecycle commands.",
    no_args_is_help=True,
)
bootstrap_app = typer.Typer(
    help="Local environment bootstrap commands.",
    no_args_is_help=True,
)
prerequisite_app = typer.Typer(
    help="External credential/prerequisite snapshot commands.",
    no_args_is_help=True,
)
app.add_typer(bootstrap_app, name="bootstrap")
app.add_typer(fixture_app, name="fixture")
app.add_typer(prerequisite_app, name="prerequisite")


WorkdirOpt = Annotated[Path | None, typer.Option("--workdir", help="testenv workdir")]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="verbose logging")]
JsonOpt = Annotated[bool, typer.Option("--json", help="print machine-readable JSON result")]


def _configure_logging(verbose: bool) -> None:
    """Initialize logging from the verbose option."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )


def _default_workdir() -> Path:
    """Return the testenv/azents workdir when discoverable."""
    here = Path(__file__).resolve()
    candidate = here.parent.parent
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


@bootstrap_app.command("local")
def cmd_bootstrap_local(
    workdir: WorkdirOpt = None,
    verbose: VerboseOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Prepare the local dev environment and devserver fixture."""
    _configure_logging(verbose)
    wd = workdir or _default_workdir()
    result = run_bootstrap_local(wd)
    if as_json:
        typer.echo(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        _print_bootstrap_local_result(result)
    raise typer.Exit(code=0 if result.status == "ready" else 1)


def _print_bootstrap_local_result(result: BootstrapLocalResult) -> None:
    """Print a human-readable bootstrap result."""
    typer.echo(f"bootstrap local: {result.status}")
    for step in result.steps:
        typer.echo(f"  [{step.status.upper()}] {step.id}: {step.message}")
    for doctor in result.doctors:
        typer.echo(f"  doctor {doctor.fixture_id}: {doctor.status}")


@prerequisite_app.command("prepare")
def cmd_prerequisite_prepare(
    profile: Annotated[
        str,
        typer.Option("--profile", help="snapshot profile name"),
    ] = DEFAULT_PREREQUISITE_PROFILE,
    max_age_seconds: Annotated[
        int,
        typer.Option("--max-age-seconds", min=1, help="snapshot TTL in seconds"),
    ] = DEFAULT_MAX_AGE_SECONDS,
    workdir: WorkdirOpt = None,
    verbose: VerboseOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Evaluate external prerequisite contracts and save a snapshot."""
    _configure_logging(verbose)
    wd = workdir or _default_workdir()
    try:
        result = prepare_prerequisite_snapshot(
            wd,
            profile=profile,
            max_age_seconds=max_age_seconds,
        )
    except PrerequisiteError as exc:
        typer.echo(f"PREREQUISITE_ERROR [{exc.detail.code}] {exc.detail.message}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if as_json:
        typer.echo(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        _print_prerequisite_prepare_result(result)
    raise typer.Exit(code=0 if result.status == "ready" else 1)


def _print_prerequisite_prepare_result(result: PrerequisitePrepareResult) -> None:
    """Print a human-readable prerequisite prepare result."""
    typer.echo(f"prerequisite {result.snapshot.profile}: {result.status}")
    typer.echo(f"  snapshot: {result.path}")
    for entry in result.snapshot.entries:
        typer.echo(f"  [{entry.status.upper()}] {entry.contract_id}")
        if entry.guidance:
            typer.echo(f"    guidance: {entry.guidance}")
        for check in entry.checks:
            typer.echo(f"    - [{check.status.upper()}] {check.id}: {check.message}")


@fixture_app.command("up")
def cmd_fixture_up(
    fixture_id: Annotated[str, typer.Argument(help="fixture id")],
    workdir: WorkdirOpt = None,
    verbose: VerboseOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Prepare a fixture and record a ready manifest."""
    _configure_logging(verbose)
    wd = workdir or _default_workdir()
    _handle_fixture_result(run_fixture_up, fixture_id, wd, as_json=as_json)


@fixture_app.command("doctor")
def cmd_fixture_doctor(
    fixture_id: Annotated[str | None, typer.Argument(help="fixture id", show_default=False)] = None,
    all_: Annotated[bool, typer.Option("--all", help="run doctor for every fixture")] = False,
    workdir: WorkdirOpt = None,
    verbose: VerboseOpt = False,
    as_json: JsonOpt = False,
) -> None:
    """Compare a fixture manifest with actual runtime state."""
    _configure_logging(verbose)
    wd = workdir or _default_workdir()
    if all_:
        results = run_fixture_doctor_all(wd)
        if as_json:
            typer.echo(
                json.dumps(
                    [result.to_json_dict() for result in results],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for index, result in enumerate(results):
                if index:
                    typer.echo("")
                _print_fixture_result(result)
        raise typer.Exit(code=0 if all(result.status == "ready" for result in results) else 1)
    if fixture_id is None:
        typer.echo("pass a fixture id or --all", err=True)
        raise typer.Exit(code=2)
    _handle_fixture_result(run_fixture_doctor, fixture_id, wd, as_json=as_json)


@fixture_app.command("reset")
def cmd_fixture_reset(
    fixture_id: Annotated[str, typer.Argument(help="fixture id")],
    workdir: WorkdirOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Remove the fixture manifest and private state."""
    _configure_logging(verbose)
    wd = workdir or _default_workdir()
    _handle_fixture_result(run_fixture_reset, fixture_id, wd, as_json=False)


def _handle_fixture_result(
    command: Callable[[str, Path], FixtureCommandResult],
    fixture_id: str,
    workdir: Path,
    *,
    as_json: bool,
) -> None:
    """Run a fixture command and print its result."""
    try:
        result = command(fixture_id, workdir)
    except UnknownFixtureError as exc:
        typer.echo(exc.detail.message, err=True)
        raise typer.Exit(code=2) from exc
    except FixtureError as exc:
        typer.echo(f"FIXTURE_ERROR [{exc.detail.code}] {exc.detail.message}", err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"ERROR {exc}", err=True)
        raise typer.Exit(code=3) from exc

    if as_json:
        typer.echo(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        _print_fixture_result(result)
    raise typer.Exit(code=0 if result.status == "ready" else 1)


def _print_fixture_result(result: FixtureCommandResult) -> None:
    """Print a human-readable fixture command result."""
    if result.status == "ready":
        typer.echo(f"fixture {result.fixture_id}: ready")
    else:
        prefix = result.error_code or "FIXTURE_ERROR"
        typer.echo(f"FIXTURE_ERROR [{prefix}] {result.message}", err=True)

    resource = _devserver_resource(result)
    if resource is not None:
        typer.echo(f"  public: {resource['public_url']}")
        typer.echo(f"  admin:  {resource['admin_url']}")
        typer.echo(f"  session: {resource['session_name']}")
    if result.manifest is not None:
        typer.echo(
            "  worktree: "
            f"{result.manifest.worktree.repo_root} @ {result.manifest.worktree.head_sha}"
        )
    if result.guidance:
        typer.echo(f"  guidance: {result.guidance}")


def _devserver_resource(result: FixtureCommandResult) -> Mapping[str, object] | None:
    """Return the devserver manifest resource payload, if present."""
    if result.manifest is None:
        return None
    resource = result.manifest.resources.get("devserver")
    if isinstance(resource, dict):
        return resource
    return None


def main() -> None:
    """Entry point for ``uv run testenv ...``."""
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
