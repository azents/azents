"""Bind synchronous public SDK dispatch to current asynchronous execution authority."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable

import anyio

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_runtime import GoogleOperationAuthorization
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.services.google_oauth.runtime import GoogleRuntimeService
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


@dataclasses.dataclass(frozen=True)
class GoogleWorkspaceExecution:
    """Caller owns typed arguments/files; runtime service owns every admission."""

    runtime: GoogleRuntimeService
    sdk: GoogleWorkspaceSdk

    async def execute[T](
        self,
        *,
        admitted: GoogleOperationAuthorization,
        limits: GoogleSdkLimits,
        proxy_url: str | None,
        operation: Callable[[GoogleSdkSession], T],
        revalidate_inputs: Callable[[], Awaitable[None]] | None,
    ) -> T:
        async def require_current() -> None:
            await self.runtime.recheck_operation(admitted)
            if revalidate_inputs is not None:
                await revalidate_inputs()
            # Input resolution/revalidation awaits external storage authority; its
            # completion does not retain a stale service/grant admission.
            await self.runtime.recheck_operation(admitted)

        def before_request() -> None:
            anyio.from_thread.run(require_current)

        try:
            await require_current()
            result = await self.sdk.run(
                access_token=admitted.snapshot.connection.candidate.tokens.access_token,
                limits=limits,
                proxy_url=proxy_url,
                before_request=before_request,
                operation=operation,
            )
        except asyncio.CancelledError:
            raise
        except GoogleSdkError as error:
            if error.status == 401:
                try:
                    await self.runtime.direct_authentication_failed(admitted)
                except CanonicalExecutionOwnerGenerationStaleError:
                    # Ownership loss defeats finalization, not the original safe
                    # provider observation. No newer grant is invalidated.
                    pass
            raise
        try:
            await require_current()
        except asyncio.CancelledError:
            raise
        except GoogleSdkError as error:
            # The SDK has returned after its operation; an input check failing
            # in this final async window cannot imply that no request was sent.
            error.dispatched = True
            raise
        except GoogleOAuthError, CanonicalExecutionOwnerGenerationStaleError:
            raise GoogleSdkError(
                "result_authority_changed",
                dispatched=True,
                status=None,
            ) from None
        return result
