"""Closed tool catalogs freeze siblings before successful writes refresh reads."""

import json

from azents.engine.events.types import (
    ClientToolCallPayload,
    NativeArtifact,
    OutputTextPart,
    build_native_compat_key,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.testing.consolidation import seed_consolidation_corpus
from azents.testing.model_selection import make_test_model_selection

_URI = "azents://memory-draft/summary.md"


def _call(call_id: str, name: str, arguments: dict[str, str]) -> ClientToolCallPayload:
    native = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="synthetic",
            native_format="test_output",
            provider="openai",
            model="gpt-4o",
            schema_version="1",
        ),
        adapter="synthetic",
        native_format="test_output",
        provider="openai",
        model="gpt-4o",
        schema_version="1",
        item={"type": "synthetic_tool_call"},
    )
    return ClientToolCallPayload(
        call_id=call_id,
        name=name,
        arguments=json.dumps(arguments),
        wire_dialect="json_function",
        native_artifact=native,
    )


async def _bindings(manager: SessionManager[WriteSession]) -> ConsolidationToolBindings:
    corpus = await seed_consolidation_corpus(manager)
    ownership = ConsolidationOwnershipRepository(manager)
    claim = await ownership.claim(corpus.team)
    assert claim is not None
    await ConsolidationRecoveryRepository(manager).prepare(claim.principal)
    return ConsolidationToolBindings(
        ConsolidationVfsObservations(claim.principal),
        ConsolidationDraftRepository(manager),
        ConsolidationSourceRepository(manager),
        ConsolidationWorkRepository(manager),
        ownership,
    )


async def test_later_sibling_uses_admission_snapshot_not_first_sibling_updated_reads(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    bindings = await _bindings(rdb_session_manager)
    selection = make_test_model_selection()
    create = bindings.admit(
        [_call("create", "write", {"path": _URI, "content": "base"})], selection
    )[0]
    assert (await create.execute()).status == "completed"
    bindings.merge(create)
    assert bindings.observations.files[_URI].content == "base"
    admitted = bindings.admit(
        [
            _call(
                "first",
                "edit",
                {"path": _URI, "old_string": "base", "new_string": "one"},
            ),
            _call(
                "second",
                "edit",
                {"path": _URI, "old_string": "one", "new_string": "two"},
            ),
        ],
        selection,
    )
    assert (await admitted[0].execute()).status == "completed"
    bindings.merge(admitted[0])
    assert bindings.observations.files[_URI].content == "one"
    second = await admitted[1].execute()
    assert second.status == "failed"
    assert any(
        "exact unambiguous context" in part.text
        for part in second.output
        if isinstance(part, OutputTextPart)
    )
    observed = await bindings.draft_repository.observe(
        bindings.observations.principal, path="summary.md"
    )
    assert observed.content == "one"


async def test_catalog_binds_only_scoped_ordinary_tools_and_rejects_runtime_and_saved(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    bindings = await _bindings(rdb_session_manager)
    selection = make_test_model_selection()
    catalog = bindings.catalog(selection, writer=bindings.observations.snapshot())
    assert set(catalog.tools) == {"read", "grep", "glob", "write", "edit", "delete"}
    calls = [
        _call("runtime", "write", {"path": "/tmp/forbidden", "content": "no"}),
        _call(
            "saved",
            "write",
            {"path": "azents://memory/saved/agent/forbidden.md", "content": "no"},
        ),
        _call("shell", "exec_command", {"command": "not executed"}),
        _call(
            "original",
            "read",
            {"path": "azents://memory/sources/team/forbidden/session.md"},
        ),
    ]
    for admitted in bindings.admit(calls, selection):
        result = await admitted.execute()
        assert result.status == "failed"
        assert (
            sum(
                len(part.text.encode("utf-8"))
                for part in result.output
                if isinstance(part, OutputTextPart)
            )
            <= 12000
        )
    assert (
        await bindings.draft_repository.inventory(bindings.observations.principal) == ()
    )
