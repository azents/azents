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
        from ottcommon.sqlalchemy.postgres import is_constrained_by

        async def create_user(user: UserModel) -> User:
            try:
                return await session.execute(sa.insert(User).values(user))
            except sa.IntegrityError as e:
                if is_constrained_by(e, "uix_users_email"):
                    raise ValueError("Email already exists")
                elif is_constrained_by(e, UserModel.UQ_USERNAME):
                    raise ValueError("Username already exists")
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
