"""Temporal interceptors for failure logging.

This module provides interceptors that log failures from workflows and activities.
It integrates with Sentry through the logging handler
(ERROR level logs are sent to Sentry).

Key considerations for Temporal's idempotency:
- Workflows can be replayed from history to recover state
- During replay, we must NOT log errors to avoid duplicates
- Activities are NOT replayed, so we always log their failures
"""

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


class _LoggingActivityInboundInterceptor(ActivityInboundInterceptor):
    """Activity interceptor that logs failures."""

    async def execute_activity(self, input: ExecuteActivityInput) -> object:
        """Execute activity and log any failures."""
        try:
            return await super().execute_activity(input)
        except Exception:
            activity.logger.exception("Activity failed")
            raise


# Define workflow interceptor class using workflow.unsafe.in_sandbox() check
# This class is instantiated in the workflow sandbox
with workflow.unsafe.imports_passed_through():

    class _LoggingWorkflowInboundInterceptor(WorkflowInboundInterceptor):
        """Workflow interceptor that logs failures only during actual execution.

        Temporal replays workflows from history to recover state. During replay,
        we skip logging to avoid duplicate error reports. We only log errors
        during actual (non-replay) execution.
        """

        async def execute_workflow(self, input: ExecuteWorkflowInput) -> object:
            """Execute workflow and log failures only when not replaying."""
            try:
                return await super().execute_workflow(input)
            except Exception:
                # Only log during actual execution, not during replay
                # This prevents duplicate logs when workflow is recovered
                if not workflow.unsafe.is_replaying():
                    workflow.logger.exception("Workflow failed")
                raise


class LoggingInterceptor(Interceptor):
    """Temporal interceptor that logs workflow and activity failures.

    This interceptor logs activity failures with context (activity_id, workflow_id,
    etc.) and workflow failures only during actual execution (not replay).
    Uses ERROR level which integrates with Sentry through logging handler.

    Example::

        from temporalio.worker import Worker
        from azcommon.temporal.interceptors import LoggingInterceptor

        worker = Worker(
            client,
            task_queue="my-queue",
            workflows=[MyWorkflow],
            activities=[my_activity],
            interceptors=[LoggingInterceptor()],
        )
    """

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        """Wrap activity execution with failure logging."""
        return _LoggingActivityInboundInterceptor(next)

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor] | None:
        """Return workflow interceptor class for failure logging."""
        return _LoggingWorkflowInboundInterceptor
