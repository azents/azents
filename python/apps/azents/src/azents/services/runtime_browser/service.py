"""Bounded public Browser projection and exact page closure operations."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserAuthority,
    BrowserCommand,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserResult,
    BrowserTarget,
)

from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.services.runtime_browser.authority import RuntimeBrowserAuthorityResolver
from azents.services.runtime_browser.data import (
    RuntimeBrowserAuthority,
    RuntimeBrowserCreatedPage,
    RuntimeBrowserOperationError,
    RuntimeBrowserProjection,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserUnavailable,
)


class RuntimeBrowserCommandRunner(Protocol):
    async def run_browser_command(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        command: BrowserCommand,
        deadline_at: datetime,
    ) -> BrowserResult: ...


@dataclass
class RuntimeBrowserService:
    authority_resolver: RuntimeBrowserAuthorityResolver
    runner_operations: RuntimeBrowserCommandRunner
    clock: Callable[[], datetime]

    async def projection(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeBrowserResource,
    ) -> RuntimeBrowserProjection:
        admission = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=self.clock(),
        )
        if isinstance(admission, RuntimeBrowserUnavailable):
            return RuntimeBrowserProjection(False, admission.reason_code, False, ())
        result = await self._dispatch(
            admission,
            BrowserObserveCommand(
                BrowserAuthority(resource.session_id, admission.working_directory),
                None,
                "status",
                False,
                16000,
            ),
        )
        await self._revalidate(admission)
        return self._projection(admission, result)

    async def create_page(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeBrowserResource,
    ) -> RuntimeBrowserCreatedPage:
        """Create one blank tab without replaying uncertain allocation."""
        admission = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=self.clock(),
        )
        if isinstance(admission, RuntimeBrowserUnavailable):
            raise RuntimeBrowserRequestError(409, "Browser is unavailable.")
        if not admission.allow_input:
            raise RuntimeBrowserRequestError(409, "Subagent sessions are read-only.")
        result = await self._dispatch(
            admission,
            BrowserOpenCommand(
                authority=BrowserAuthority(
                    resource.session_id, admission.working_directory
                ),
                task_id=None,
                url=None,
                label="Browser",
            ),
        )
        projection = self._projection(admission, result)
        page = result.page
        if page is None or not any(
            page == current for task in result.tasks for current in task.pages
        ):
            raise RuntimeBrowserOperationError(
                "Browser tab creation was not confirmed; do not replay the action."
            )
        await self._revalidate(admission)
        return RuntimeBrowserCreatedPage(projection, page)

    async def close_page(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeBrowserResource,
        task_id: str,
        page_id: str,
        resource_incarnation: str,
    ) -> RuntimeBrowserProjection:
        admission = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=self.clock(),
        )
        if isinstance(admission, RuntimeBrowserUnavailable):
            raise RuntimeBrowserRequestError(409, "Browser is unavailable.")
        if not admission.allow_input:
            raise RuntimeBrowserRequestError(409, "Subagent sessions are read-only.")
        result = await self._dispatch(
            admission,
            BrowserActCommand(
                authority=BrowserAuthority(
                    resource.session_id, admission.working_directory
                ),
                target=BrowserTarget(task_id, page_id, resource_incarnation, None),
                action=BrowserAction(
                    kind="close_page",
                    ref=None,
                    observation_id=None,
                    text=None,
                    encrypted_text=None,
                    url=None,
                    values=None,
                    checked=None,
                    key=None,
                    x=None,
                    y=None,
                    end_ref=None,
                    paths=None,
                    dialog_id=None,
                    accept=None,
                    condition=None,
                    expect=None,
                    timeout_ms=10000,
                ),
            ),
        )
        if result.action_state != "dispatched" or any(
            page.id == page_id and page.resource_incarnation == resource_incarnation
            for task in result.tasks
            for page in task.pages
        ):
            raise RuntimeBrowserOperationError(
                "Browser closure was not confirmed; do not replay the action."
            )
        await self._revalidate(admission)
        return self._projection(admission, result)

    async def _revalidate(self, authority: RuntimeBrowserAuthority) -> None:
        current = await self.authority_resolver.resolve(
            user_id=authority.user_id,
            authentication_session_id=authority.authentication_session_id,
            resource=authority.resource,
            resolved_at=self.clock(),
        )
        if current != authority:
            raise RuntimeBrowserRequestError(
                409, "Browser authority changed; refresh current state."
            )

    async def _dispatch(
        self, authority: RuntimeBrowserAuthority, command: BrowserCommand
    ) -> BrowserResult:
        try:
            return await self.runner_operations.run_browser_command(
                runtime_id=authority.target.id,
                runner_generation=authority.target.runner_generation,
                owner_session_id=authority.resource.session_id,
                command=command,
                deadline_at=self.clock() + timedelta(seconds=15),
            )
        except asyncio.CancelledError:
            raise
        except (
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationCanceledError,
        ):
            raise RuntimeBrowserRequestError(
                409, "Browser operation did not complete; refresh current state."
            ) from None
        except RuntimeRunnerOperationFailedError as error:
            if error.code in {
                "browser_stale_target",
                "browser_invalid_target",
                "browser_input_conflict",
                "browser_dialog_pending",
                "browser_stale_generation",
                "browser_invalid_authority",
                "browser_resource_exhausted",
            }:
                raise RuntimeBrowserRequestError(
                    409, "Browser target is unavailable or conflicting; refresh state."
                ) from None
            raise RuntimeBrowserOperationError(
                "Browser operation failed; do not replay an uncertain action."
            ) from None

    @staticmethod
    def _projection(
        authority: RuntimeBrowserAuthority, result: BrowserResult
    ) -> RuntimeBrowserProjection:
        task_ids: set[str] = set()
        page_ids: set[str] = set()
        for task in result.tasks:
            if task.id in task_ids:
                raise RuntimeBrowserOperationError(
                    "Browser returned an invalid task list."
                )
            task_ids.add(task.id)
            for page in task.pages:
                if page.task_id != task.id or page.id in page_ids:
                    raise RuntimeBrowserOperationError(
                        "Browser returned an invalid page list."
                    )
                page_ids.add(page.id)
        return RuntimeBrowserProjection(True, None, authority.allow_input, result.tasks)
