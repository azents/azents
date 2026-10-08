"""Own concurrent selected-image preparation across separate readiness joins."""

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from types import TracebackType
from typing import Literal, Self


class ImagePreparationError(RuntimeError):
    """Expose one failed image without including builder authentication output."""

    def __init__(self, image: str, error_class: str) -> None:
        self.image = image
        self.error_class = error_class
        super().__init__(f"E2E image {image} preparation failed ({error_class}).")


def _raise_errors(errors: list[BaseException]) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("E2E image preparation failed", errors)


def _prepare_image(image: str, operation: Callable[[], str]) -> str:
    try:
        return operation()
    except Exception as error:
        raise ImagePreparationError(image, type(error).__name__) from None


class E2EImagePreparation:
    """Own one build batch, publishing images only after successful completion."""

    def __init__(
        self,
        prepared_images: Mapping[str, str],
        build_operations: Mapping[str, Callable[[], str]],
    ) -> None:
        if prepared_images.keys() & build_operations.keys():
            raise ValueError("Prepared images cannot also have build operations.")
        self.prepared_images = dict(prepared_images)
        self.build_operations = dict(build_operations)
        self.selected_images = (*prepared_images, *build_operations)
        self.futures: dict[str, Future[str]] = {}
        self.reported_failures: set[str] = set()
        self.executor: ThreadPoolExecutor | None = None
        self.entered = False
        self.closed = False

    def __enter__(self) -> Self:
        if self.entered or self.closed:
            raise RuntimeError("E2E image preparation can be entered only once.")
        self.entered = True
        try:
            if self.build_operations:
                self.executor = ThreadPoolExecutor(
                    max_workers=len(self.build_operations)
                )
                for image, operation in self.build_operations.items():
                    self.futures[image] = self.executor.submit(
                        _prepare_image, image, operation
                    )
        except BaseException as primary:
            try:
                self.close()
            except BaseException as secondary:
                raise BaseExceptionGroup(
                    "E2E image preparation entry failed", [primary, secondary]
                ) from None
            raise
        return self

    def join(self, images: Iterable[str]) -> dict[str, str]:
        """Observe all requested outcomes before returning a complete ready view."""
        if not self.entered or self.closed:
            raise RuntimeError("E2E image preparation is not active.")
        requested = tuple(dict.fromkeys(images))
        unknown = set(requested) - set(self.selected_images)
        if unknown:
            raise ValueError("Cannot join images outside the selected portfolio.")
        ready: dict[str, str] = {}
        errors: list[BaseException] = []
        for image in requested:
            if image in self.prepared_images:
                ready[image] = self.prepared_images[image]
                continue
            future = self.futures[image]
            try:
                ready[image] = future.result()
            except BaseException as error:
                # An interrupt of result() is not a terminal worker failure.
                if future.done() and (
                    future.cancelled() or future.exception() is error
                ):
                    self.reported_failures.add(image)
                errors.append(error)
        _raise_errors(errors)
        return ready

    def close(self) -> None:
        """Drain every submitted build and report only unreported failures."""
        if self.closed:
            return
        errors: list[BaseException] = []
        try:
            for image, future in self.futures.items():
                while not future.done():
                    try:
                        future.result()
                    except BaseException as error:
                        if not (
                            future.done()
                            and (future.cancelled() or future.exception() is error)
                        ):
                            # Finish ownership before propagating interruption.
                            errors.append(error)
                if image in self.reported_failures:
                    continue
                try:
                    future.result()
                except BaseException as error:
                    self.reported_failures.add(image)
                    errors.append(error)
        finally:
            if self.executor is not None:
                self.executor.shutdown(wait=True, cancel_futures=False)
            self.closed = True
        _raise_errors(errors)

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exception_type, traceback
        try:
            self.close()
        except BaseException as secondary:
            if exception is not None:
                raise BaseExceptionGroup(
                    "E2E preparation and image drain failed", [exception, secondary]
                ) from None
            raise
        return False
