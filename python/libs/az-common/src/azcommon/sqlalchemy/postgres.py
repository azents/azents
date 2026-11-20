import psycopg
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError


def is_constrained_by(
    e: IntegrityError,
    constraint: (
        str | sa.UniqueConstraint | sa.ForeignKeyConstraint | sa.PrimaryKeyConstraint
    ),
) -> bool:
    """
    Check if the integrity error is constrained by the given constraint.

    .. code-block:: python

        import sqlalchemy as sa
        from sqlalchemy.exc import IntegrityError

        from azcommon.sqlalchemy.postgres import is_constrained_by

        async def create_user(email: str, username: str) -> None:
            try:
                await session.execute(
                    sa.insert(User).values(email=email, username=username)
                )
            except IntegrityError as e:
                if is_constrained_by(e, "uix_users_email"):
                    raise ValueError("Email already exists") from e
                if is_constrained_by(e, "uix_users_username"):
                    raise ValueError("Username already exists") from e
                raise

    """
    if not isinstance(constraint, str):
        name = constraint.name
        if not isinstance(name, str):
            return False
        return is_constrained_by(e, name)
    orig = e.orig
    if not isinstance(orig, psycopg.errors.IntegrityError):
        return False
    constraint_name = orig.diag.constraint_name
    return bool(constraint_name == constraint)
