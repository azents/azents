"""PostgreSQL evidence for retirement of persisted inbound policy authority."""

import datetime

import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from azcommon.uuid import uuid7
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from azents.consts import PROJECT_ROOT
from azents.core.system_setting import (
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.rdb.models.system_setting import RDBSystemSetting, RDBSystemSettingCandidate


@pytest.mark.asyncio
@pytest.mark.parametrize("old_inbound_bytes", [10 * 1024 * 1024, 500 * 1024 * 1024])
async def test_retirement_preserves_outbound_and_invalidates_stale_version(
    rdb_session: AsyncSession,
    old_inbound_bytes: int,
) -> None:
    """Both customized and historical defaults lose inbound authority only."""
    now = datetime.datetime.now(datetime.UTC)
    section = SystemSettingSection.EXTERNAL_CHANNEL_FILES
    outbound = {
        "outbound_max_file_bytes": 20 * 1024 * 1024,
        "outbound_max_action_bytes": 60 * 1024 * 1024,
    }
    legacy_config = {"inbound_max_file_bytes": old_inbound_bytes, **outbound}
    rdb_session.add(
        RDBSystemSetting(
            section=section,
            schema_version=1,
            version=7,
            config=legacy_config,
            validation_status=SystemSettingValidationStatus.VALID,
            validated_generation="a" * 64,
            validation_metadata={"validated": True},
            validated_at=now,
        )
    )
    rdb_session.add(
        RDBSystemSettingCandidate(
            id=uuid7().hex,
            section=section,
            schema_version=1,
            base_version=7,
            config=legacy_config,
            validation_status=SystemSettingValidationStatus.VALID,
            created_at=now,
            updated_at=now,
            expires_at=now + datetime.timedelta(days=1),
        )
    )
    await rdb_session.flush()
    config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("43a0fbdc96fe")
    assert revision is not None

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()

    connection = await rdb_session.connection()
    await connection.run_sync(upgrade)
    rdb_session.expire_all()
    current = (await rdb_session.execute(sa.select(RDBSystemSetting))).scalar_one()
    candidate = (
        await rdb_session.execute(sa.select(RDBSystemSettingCandidate))
    ).scalar_one()
    assert current.config == outbound
    assert current.schema_version == 2
    assert current.version == 8
    assert current.validated_generation is None
    assert current.validation_metadata is None
    assert current.validation_status is None
    assert current.validated_at is None
    assert candidate.config == outbound
    assert candidate.schema_version == 2
    assert candidate.base_version == 7

    def downgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.downgrade()

    await connection.run_sync(downgrade)
    rdb_session.expire_all()
    restored = (await rdb_session.execute(sa.select(RDBSystemSetting))).scalar_one()
    assert restored.schema_version == 1
    assert restored.config == {**outbound, "inbound_max_file_bytes": 134_217_728}
