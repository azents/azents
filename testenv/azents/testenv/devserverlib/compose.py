"""Docker Compose helpers."""

import subprocess

import typer

from .paths import COMPOSE_FILE, COMPOSE_PROJECT

# `rustfs-init` is a one-off container. Including it in `--wait` makes Docker
# Compose treat the expected "exited" state as a failure, so we wait only for
# long-running services and run `rustfs-init` after `rustfs` is healthy.
_LONG_RUNNING_SERVICES = ("db", "valkey", "rustfs")


def compose_up() -> None:
    """`docker compose ... up -d --wait <long-running services>`."""
    typer.echo("[compose] up -d --wait (long-running services)")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            COMPOSE_PROJECT,
            "up",
            "-d",
            "--wait",
            "--remove-orphans",
            *_LONG_RUNNING_SERVICES,
        ],
        check=True,
    )
    typer.echo("[compose] run rustfs-init")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            COMPOSE_PROJECT,
            "up",
            "--no-deps",
            "rustfs-init",
        ],
        check=True,
    )


def compose_down() -> None:
    typer.echo("[compose] down")
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            COMPOSE_PROJECT,
            "down",
        ],
        check=False,
    )
