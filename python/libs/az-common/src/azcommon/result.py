import dataclasses
from typing import Generic, Literal, NoReturn, TypeVar

S = TypeVar("S")
F = TypeVar("F")


@dataclasses.dataclass(frozen=True)
class Success(Generic[S]):
    """
    Successful result containing a value of type S.
    """

    value: S

    @property
    def success(self) -> Literal[True]:
        """
        Return whether the result is successful.
        """
        return True

    @property
    def failure(self) -> Literal[False]:
        """
        Return whether the result is a failure.
        """
        return False

    @property
    def error(self) -> NoReturn:
        """
        Raise AttributeError because a successful result has no error.

        This property supports static narrowing of the Result union.
        """
        raise AttributeError("Success has no error")


@dataclasses.dataclass(frozen=True)
class Failure(Generic[F]):
    """
    Failed result containing an error of type F.
    """

    error: F

    @property
    def success(self) -> Literal[False]:
        """
        Return whether the result is successful.
        """
        return False

    @property
    def failure(self) -> Literal[True]:
        """
        Return whether the result is a failure.
        """
        return True

    @property
    def value(self) -> NoReturn:
        """
        Raise AttributeError because a failed result has no value.

        This property supports static narrowing of the Result union.
        """
        raise AttributeError("Failure has no value")


Result = Success[S] | Failure[F]
