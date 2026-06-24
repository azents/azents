import dataclasses
from typing import Generic, Literal, NoReturn, TypeVar

S = TypeVar("S")
F = TypeVar("F")


@dataclasses.dataclass(frozen=True)
class Success(Generic[S]):
    """
    타입 S의 값을 가진 성공 결과
    """

    value: S

    @property
    def success(self) -> Literal[True]:
        """
        결과가 성공인지 여부
        """
        return True

    @property
    def failure(self) -> Literal[False]:
        """
        결과가 실패인지 여부
        """
        return False

    @property
    def error(self) -> NoReturn:
        """
        Success에는 error가 없으므로 접근 시 AttributeError 발생.
        pyright의 union 타입 narrowing 지원을 위해 정의됨.
        """
        raise AttributeError("Success has no error")


@dataclasses.dataclass(frozen=True)
class Failure(Generic[F]):
    """
    타입 F의 에러를 가진 실패 결과
    """

    error: F

    @property
    def success(self) -> Literal[False]:
        """
        결과가 성공인지 여부
        """
        return False

    @property
    def failure(self) -> Literal[True]:
        """
        결과가 실패인지 여부
        """
        return True

    @property
    def value(self) -> NoReturn:
        """
        Failure에는 value가 없으므로 접근 시 AttributeError 발생.
        pyright의 union 타입 narrowing 지원을 위해 정의됨.
        """
        raise AttributeError("Failure has no value")


Result = Success[S] | Failure[F]
