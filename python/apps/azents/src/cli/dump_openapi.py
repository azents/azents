"""CLI for generating OpenAPI specs."""

from enum import Enum
from typing import Annotated

import typer

from azents.app import (
    ADMIN_OPENAPI_SPEC_PATH,
    PUBLIC_OPENAPI_SPEC_PATH,
    create_dummy_admin_app,
    create_dummy_public_app,
    dump_openapi_spec,
)


class Target(str, Enum):
    """Application target for OpenAPI spec generation."""

    ALL = "all"
    PUBLIC = "public"
    ADMIN = "admin"


def _dump_public() -> None:
    dummy_app = create_dummy_public_app()
    output_path = PUBLIC_OPENAPI_SPEC_PATH
    dump_openapi_spec(output_path, dummy_app)
    typer.echo(f"Dumped public openapi to {output_path}")


def _dump_admin() -> None:
    dummy_app = create_dummy_admin_app()
    output_path = ADMIN_OPENAPI_SPEC_PATH
    dump_openapi_spec(output_path, dummy_app)
    typer.echo(f"Dumped admin openapi to {output_path}")


def main(
    target: Annotated[
        Target,
        typer.Option(
            help="Target app (all, public, admin)",
        ),
    ] = Target.ALL,
) -> None:
    """Dump OpenAPI specs.

    Select which app to generate with ``--target``:
    - all: generate both Public and Admin specs (default)
    - public: Public API spec
    - admin: Admin API spec
    """
    if target == Target.ALL:
        _dump_public()
        _dump_admin()
    elif target == Target.PUBLIC:
        _dump_public()
    elif target == Target.ADMIN:
        _dump_admin()


if __name__ == "__main__":
    typer.run(main)
