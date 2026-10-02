"""Toolkit dependency-composition tests."""

from unittest.mock import AsyncMock

from azents.engine.tools.deps import get_vfs_read_router
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.services.memory_vfs import MemoryVfsReadBackend
from azents.services.vfs_read import SkillsVfsReadBackend


def test_vfs_read_router_registers_skills_and_memory_backends() -> None:
    """Composition exposes each approved VFS mount through one registry."""
    session_manager = AsyncMock()
    projection_service = AsyncMock()
    memory_repository = MemoryVfsRepository(session_manager=session_manager)

    router = get_vfs_read_router(
        session_manager=session_manager,
        projection_service=projection_service,
        memory_repository=memory_repository,
    )

    assert router.registry.mounts == ("memory", "skills")
    assert isinstance(router.registry.get("skills"), SkillsVfsReadBackend)
    memory_backend = router.registry.get("memory")
    assert isinstance(memory_backend, MemoryVfsReadBackend)
    assert memory_backend.repository is memory_repository
