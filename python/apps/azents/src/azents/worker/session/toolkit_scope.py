"""toolkit lifecycle scope managed by SessionRunner."""

from collections.abc import Sequence

from azents.engine.run.contracts import ToolkitBinding
from azents.engine.tooling.session_toolkits import (
    SessionToolkitBinding,
    SessionToolkitKey,
    SessionToolkitLifecycle,
)


def session_toolkit_key(
    *,
    binding: ToolkitBinding,
) -> SessionToolkitKey:
    """Create stable key used by Session lifecycle registry."""
    if binding.toolkit_type is not None:
        toolkit_source_id = binding.toolkit_config_id or binding.slug
        return SessionToolkitKey(
            namespace=f"registered:{binding.toolkit_type}",
            name=toolkit_source_id,
        )
    return SessionToolkitKey(
        namespace="auto",
        name=binding.slug,
    )


class SessionToolkitScope:
    """Manage Session-managed toolkit lifecycle."""

    def __init__(self) -> None:
        self.lifecycle = SessionToolkitLifecycle()

    async def prepare(
        self,
        toolkits: Sequence[ToolkitBinding],
    ) -> list[ToolkitBinding]:
        """Reconcile desired toolkit binding to session-managed binding."""
        desired = [
            SessionToolkitBinding(
                key=session_toolkit_key(
                    binding=binding,
                ),
                binding=binding,
            )
            for binding in toolkits
        ]
        return await self.lifecycle.reconcile(desired)

    async def cleanup(self) -> None:
        """Close Session-managed toolkit context."""
        await self.lifecycle.close()
