"""Contained Git operation kernels and process lifecycle."""

import hashlib
import os
import selectors
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, assert_never

from azents_runtime_runner.contained_kernels import _resolve_lexical_path
from azents_runtime_runner.contained_protocol import JsonValue
from azents_runtime_runner.contained_requests import (
    GitCreateWorktreeRequest,
    GitDeleteBranchRequest,
    GitDiscoverManagedWorktreesRequest,
    GitInspectWorktreeRequest,
    GitListRefsRequest,
    GitRemoveDiscoveredWorktreeRequest,
    GitRemoveWorktreeRequest,
    GitRequest,
)
from azents_runtime_runner.workspace import Workspace

_GIT_PATH = "/usr/bin/git"
_PROCESS_READ_CHUNK_BYTES = 4096
_TERMINATE_TIMEOUT_SECONDS = 2.0
_KILL_TIMEOUT_SECONDS = 2.0
_MANAGED_WORKTREE_ROOT = ".azents/worktrees"
_MAX_MANAGED_WORKTREE_DISCOVERY_ENTRIES = 512

GitEventEmitter = Callable[[str, Mapping[str, JsonValue], bool], None]


@dataclass(frozen=True)
class _GitCommandResult:
    """Completed Git command output."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class _GitWorktreeInspection:
    """Content-free Git worktree registration and filesystem observation."""

    worktree_path: Path
    registered: bool
    registered_branch_name: str | None
    target_kind: Literal["directory", "missing", "other"]
    dirty: bool | None


@dataclass(frozen=True)
class _GitWorktreeRegistration:
    """Exact Git worktree registration observation."""

    registered: bool
    branch_name: str | None


@dataclass(frozen=True)
class _DiscoveredWorktree:
    """Typed managed-worktree discovery observation."""

    worktree_path: Path
    registered: bool
    repository_anchor_path: str
    branch_name: str
    fingerprint: str
    failure_code: str

    def payload(self) -> dict[str, JsonValue]:
        return {
            "worktree_path": str(self.worktree_path),
            "registered": self.registered,
            "repository_anchor_path": self.repository_anchor_path,
            "branch_name": self.branch_name,
            "fingerprint": self.fingerprint,
            "failure_code": self.failure_code,
        }


class _GitCancelled(Exception):
    """Contained Git execution was cancelled by the trusted client."""


class _ContainedGitOperations:
    def __init__(
        self,
        *,
        workspace: Workspace,
        cancellation: threading.Event,
        deadline_at: datetime | None,
        emit: GitEventEmitter,
    ) -> None:
        self.workspace = workspace
        self.cancellation = cancellation
        self.deadline_at = deadline_at
        self.emit = emit

    def run(self, request: GitRequest) -> None:
        try:
            match request:
                case GitListRefsRequest():
                    self._list_refs(request)
                case GitCreateWorktreeRequest():
                    self._create_worktree(request)
                case GitInspectWorktreeRequest():
                    self._inspect_worktree_operation(request)
                case GitDiscoverManagedWorktreesRequest():
                    self._discover_managed_worktrees()
                case GitRemoveDiscoveredWorktreeRequest():
                    self._remove_discovered_worktree(request)
                case GitRemoveWorktreeRequest():
                    self._remove_worktree(request)
                case GitDeleteBranchRequest():
                    self._delete_branch(request)
                case _ as unreachable:
                    assert_never(unreachable)
        except _GitCancelled:
            return

    def _success(self, payload: Mapping[str, JsonValue]) -> None:
        self.emit("final_success", payload, True)

    def _error(self, code: str, message: str) -> None:
        self.emit(
            "final_error",
            {"error_code": code, "error_message": message},
            True,
        )

    def _list_refs(self, request: GitListRefsRequest) -> None:
        source_path = self._source_path(request.source_project_path)
        if source_path is None:
            return
        refs_result = self._run_git(
            ("for-each-ref", "--format=%(refname)%09%(objectname)%09%(refname:short)"),
            cwd=source_path,
            stream_output=False,
        )
        if refs_result is None:
            return
        if refs_result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(refs_result))
            return
        default_branch = self._default_branch(source_path)
        head_commit = self._head_commit(source_path)
        refs: list[JsonValue] = []
        for line in refs_result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            ref, target, short_name = parts
            refs.append(
                {
                    "name": _git_ref_display_name(ref, short_name),
                    "ref": ref,
                    "type": _git_ref_type(ref),
                    "target": target,
                    "default": _git_ref_is_default(ref, short_name, default_branch),
                }
            )
        self._success(
            {
                "git_refs": refs,
                "default_branch": default_branch,
                "head_commit": head_commit,
            }
        )

    def _create_worktree(self, request: GitCreateWorktreeRequest) -> None:
        source_path = self._source_path(request.source_project_path)
        if source_path is None:
            return
        starting_ref = request.starting_ref
        if not starting_ref:
            self._error("invalid_ref", "starting_ref is required")
            return
        branch_name = request.branch_name
        if not branch_name:
            self._error("invalid_branch", "branch_name is required")
            return
        try:
            worktree_path = _resolve_lexical_path(
                request.worktree_path,
                workspace=self.workspace,
            )
        except ValueError as error:
            self._error("invalid_worktree_path", str(error))
            return
        if worktree_path.exists() or worktree_path.is_symlink():
            self._error(
                "worktree_path_exists",
                f"Worktree path already exists: {worktree_path}",
            )
            return
        base_commit = self._resolve_commit(source_path, starting_ref)
        if base_commit is None:
            return
        branch_exists = self._branch_exists(source_path, branch_name)
        if branch_exists is None:
            return
        if branch_exists:
            self._error("branch_exists", f"Git branch already exists: {branch_name}")
            return
        result = self._run_git(
            (
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                starting_ref,
            ),
            cwd=source_path,
            stream_output=True,
        )
        if result is None:
            return
        if result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(result))
            return
        self._success(
            {
                "base_commit": base_commit,
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
            }
        )

    def _inspect_worktree_operation(
        self,
        request: GitInspectWorktreeRequest,
    ) -> None:
        source_path = self._source_path(request.source_project_path)
        if source_path is None:
            return
        inspection = self._inspect_worktree(source_path, request.worktree_path)
        if inspection is None:
            return
        payload: dict[str, JsonValue] = {
            "worktree_path": str(inspection.worktree_path),
            "worktree_registered": inspection.registered,
            "target_kind": inspection.target_kind,
        }
        if inspection.registered_branch_name is not None:
            payload["registered_branch_name"] = inspection.registered_branch_name
        if inspection.dirty is not None:
            payload["dirty"] = inspection.dirty
        self._success(payload)

    def _discover_managed_worktrees(self) -> None:
        root = self.workspace.root / _MANAGED_WORKTREE_ROOT
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            self._error(
                "managed_worktree_root_invalid",
                "Managed worktree root is not a directory.",
            )
            return
        if not root.exists():
            self._success({"discovered_worktrees": []})
            return
        entries: list[JsonValue] = []
        for session_directory in sorted(root.iterdir(), key=lambda path: path.name):
            self._check_stop()
            if session_directory.is_symlink() or not session_directory.is_dir():
                continue
            direct_entry = self._discover_entry(session_directory)
            if direct_entry.registered:
                if not self._append_discovered(entries, direct_entry):
                    return
                continue
            for candidate in sorted(
                session_directory.iterdir(), key=lambda path: path.name
            ):
                self._check_stop()
                if candidate.is_symlink() or not candidate.is_dir():
                    continue
                if not self._append_discovered(
                    entries,
                    self._discover_entry(candidate),
                ):
                    return
        self._success({"discovered_worktrees": entries})

    def _append_discovered(
        self,
        entries: list[JsonValue],
        entry: _DiscoveredWorktree,
    ) -> bool:
        if len(entries) >= _MAX_MANAGED_WORKTREE_DISCOVERY_ENTRIES:
            self._error(
                "managed_worktree_inventory_overflow",
                "Managed worktree inventory exceeds the operation limit.",
            )
            return False
        entries.append(entry.payload())
        return True

    def _discover_entry(self, candidate: Path) -> _DiscoveredWorktree:
        if candidate.is_symlink() or not candidate.is_dir():
            return _discovered_worktree(
                candidate,
                registered=False,
                repository_anchor_path="",
                branch_name="",
                failure_code="worktree_ownership_ambiguous",
            )
        result = self._run_git(
            ("worktree", "list", "--porcelain", "-z"),
            cwd=candidate,
            stream_output=False,
        )
        if result is None or result.exit_code != 0:
            return _discovered_worktree(
                candidate,
                registered=False,
                repository_anchor_path="",
                branch_name="",
                failure_code="not_git_worktree",
            )
        registration = _registered_worktree(result.stdout, worktree_path=candidate)
        if not registration.registered:
            return _discovered_worktree(
                candidate,
                registered=False,
                repository_anchor_path="",
                branch_name="",
                failure_code="worktree_ownership_ambiguous",
            )
        anchor_result = self._run_git(
            ("rev-parse", "--path-format=absolute", "--git-common-dir"),
            cwd=candidate,
            stream_output=False,
        )
        head_result = self._run_git(
            ("rev-parse", "HEAD"), cwd=candidate, stream_output=False
        )
        if (
            anchor_result is None
            or anchor_result.exit_code != 0
            or head_result is None
            or head_result.exit_code != 0
        ):
            return _discovered_worktree(
                candidate,
                registered=False,
                repository_anchor_path="",
                branch_name="",
                failure_code="worktree_ownership_ambiguous",
            )
        repository_anchor_path = Path(anchor_result.stdout.strip())
        if not _path_is_within(repository_anchor_path, self.workspace.root):
            return _discovered_worktree(
                candidate,
                registered=False,
                repository_anchor_path="",
                branch_name="",
                failure_code="worktree_ownership_ambiguous",
            )
        return _discovered_worktree(
            candidate,
            registered=True,
            repository_anchor_path=str(repository_anchor_path),
            branch_name=registration.branch_name or "",
            head_commit=head_result.stdout.strip(),
            failure_code="",
        )

    def _remove_discovered_worktree(
        self,
        request: GitRemoveDiscoveredWorktreeRequest,
    ) -> None:
        try:
            worktree_path = _resolve_lexical_path(
                request.worktree_path, workspace=self.workspace
            )
        except ValueError as error:
            self._error("invalid_worktree_path", str(error))
            return
        managed_root = self.workspace.root / _MANAGED_WORKTREE_ROOT
        if not _path_is_within(worktree_path, managed_root):
            self._error(
                "worktree_ownership_ambiguous",
                "Worktree path is outside the managed root.",
            )
            return
        if not worktree_path.exists():
            try:
                repository_anchor_path = _resolve_lexical_path(
                    request.repository_anchor_path,
                    workspace=self.workspace,
                )
            except ValueError as error:
                self._error("worktree_ownership_ambiguous", str(error))
                return
            if not _path_is_within(repository_anchor_path, self.workspace.root):
                self._error(
                    "worktree_ownership_ambiguous",
                    "Worktree repository metadata is outside the Agent Workspace.",
                )
                return
            result = self._run_git(
                (
                    "--git-dir",
                    str(repository_anchor_path),
                    "worktree",
                    "remove",
                    "--force",
                    str(worktree_path),
                ),
                cwd=self.workspace.root,
                stream_output=True,
            )
            if result is None:
                return
            if result.exit_code != 0:
                self._error("git_command_failed", _git_command_error_message(result))
                return
            self._success(
                {
                    "removed_discovered_worktree_path": str(worktree_path),
                    "outcome": "already_absent",
                }
            )
            return
        observed = self._discover_entry(worktree_path)
        if not observed.registered:
            self._error(
                observed.failure_code or "worktree_ownership_ambiguous",
                "Managed worktree identity could not be revalidated.",
            )
            return
        expected = (
            request.repository_anchor_path,
            request.branch_name,
            request.fingerprint,
        )
        actual = (
            observed.repository_anchor_path,
            observed.branch_name,
            observed.fingerprint,
        )
        if expected != actual or not request.force:
            self._error(
                "identity_changed",
                "Managed worktree identity changed after discovery.",
            )
            return
        result = self._run_git(
            ("worktree", "remove", "--force", str(worktree_path)),
            cwd=worktree_path,
            stream_output=True,
        )
        if result is None:
            return
        if result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(result))
            return
        self._success(
            {
                "removed_discovered_worktree_path": str(worktree_path),
                "outcome": "removed",
            }
        )

    def _remove_worktree(self, request: GitRemoveWorktreeRequest) -> None:
        source_path = self._source_path(request.source_project_path)
        if source_path is None:
            return
        inspection = self._inspect_worktree(source_path, request.worktree_path)
        if inspection is None:
            return
        expected_branch_name = request.branch_name
        if not expected_branch_name:
            self._error("invalid_branch", "branch_name is required")
            return
        if inspection.target_kind == "other":
            self._error(
                "worktree_ownership_ambiguous",
                "Recorded worktree target is not a directory.",
            )
            return
        if (
            inspection.registered
            and inspection.registered_branch_name != expected_branch_name
        ):
            self._error(
                "worktree_ownership_ambiguous",
                "Git worktree registration does not match the recorded branch.",
            )
            return
        if inspection.target_kind == "directory" and not inspection.registered:
            self._error(
                "worktree_ownership_ambiguous",
                (
                    "Existing worktree target does not match the recorded Git "
                    "registration."
                ),
            )
            return
        if inspection.target_kind == "missing" and not inspection.registered:
            self._success(
                {
                    "removed_worktree_path": str(inspection.worktree_path),
                    "outcome": "already_absent",
                }
            )
            return
        argv = ["worktree", "remove"]
        if request.force:
            argv.append("--force")
        argv.append(str(inspection.worktree_path))
        result = self._run_git(tuple(argv), cwd=source_path, stream_output=True)
        if result is None:
            return
        if result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(result))
            return
        self._success(
            {
                "removed_worktree_path": str(inspection.worktree_path),
                "outcome": (
                    "already_absent"
                    if inspection.target_kind == "missing"
                    else "removed"
                ),
            }
        )

    def _delete_branch(self, request: GitDeleteBranchRequest) -> None:
        source_path = self._source_path(request.source_project_path)
        if source_path is None:
            return
        branch_name = request.branch_name
        if not branch_name:
            self._error("invalid_branch", "branch_name is required")
            return
        branch_exists = self._branch_exists(source_path, branch_name)
        if branch_exists is None:
            return
        if not branch_exists:
            self._success(
                {"deleted_branch_name": branch_name, "outcome": "already_absent"}
            )
            return
        result = self._run_git(
            ("branch", "-D", branch_name), cwd=source_path, stream_output=True
        )
        if result is None:
            return
        if result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(result))
            return
        self._success({"deleted_branch_name": branch_name, "outcome": "deleted"})

    def _source_path(self, source_project_path: str) -> Path | None:
        try:
            source_path = _resolve_lexical_path(
                source_project_path, workspace=self.workspace
            )
        except ValueError as error:
            self._error("invalid_source_path", str(error))
            return None
        if not source_path.exists():
            self._error(
                "not_git_repo",
                f"Source project path does not exist: {source_path}",
            )
            return None
        if not source_path.is_dir():
            self._error(
                "not_git_repo",
                f"Source project path is not a directory: {source_path}",
            )
            return None
        result = self._run_git(
            ("rev-parse", "--is-inside-work-tree"),
            cwd=source_path,
            stream_output=False,
        )
        if result is None:
            return None
        if result.exit_code != 0 or result.stdout.strip() != "true":
            self._error(
                "not_git_repo",
                f"Source project path is not a Git repository: {source_path}",
            )
            return None
        return source_path

    def _resolve_commit(self, source_path: Path, ref: str) -> str | None:
        result = self._run_git(
            ("rev-parse", "--verify", f"{ref}^{{commit}}"),
            cwd=source_path,
            stream_output=False,
        )
        if result is None:
            return None
        if result.exit_code != 0:
            self._error("invalid_ref", _git_command_error_message(result))
            return None
        return result.stdout.strip()

    def _branch_exists(self, source_path: Path, branch_name: str) -> bool | None:
        result = self._run_git(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"),
            cwd=source_path,
            stream_output=False,
        )
        if result is None:
            return None
        if result.exit_code == 0:
            return True
        if result.exit_code == 1:
            return False
        self._error("git_command_failed", _git_command_error_message(result))
        return None

    def _inspect_worktree(
        self,
        source_path: Path,
        requested_worktree_path: str,
    ) -> _GitWorktreeInspection | None:
        try:
            worktree_path = _resolve_lexical_path(
                requested_worktree_path,
                workspace=self.workspace,
            )
        except ValueError as error:
            self._error("invalid_worktree_path", str(error))
            return None
        result = self._run_git(
            ("worktree", "list", "--porcelain", "-z"),
            cwd=source_path,
            stream_output=False,
        )
        if result is None:
            return None
        if result.exit_code != 0:
            self._error("git_command_failed", _git_command_error_message(result))
            return None
        registration = _registered_worktree(result.stdout, worktree_path=worktree_path)
        if worktree_path.is_symlink():
            target_kind: Literal["directory", "missing", "other"] = "other"
        elif worktree_path.is_dir():
            target_kind = "directory"
        elif worktree_path.exists():
            target_kind = "other"
        else:
            target_kind = "missing"
        dirty: bool | None = None
        if registration.registered and target_kind == "directory":
            status = self._run_git(
                ("status", "--porcelain", "--untracked-files=normal"),
                cwd=worktree_path,
                stream_output=False,
            )
            if status is None:
                return None
            if status.exit_code != 0:
                self._error("git_command_failed", _git_command_error_message(status))
                return None
            dirty = bool(status.stdout)
        return _GitWorktreeInspection(
            worktree_path=worktree_path,
            registered=registration.registered,
            registered_branch_name=registration.branch_name,
            target_kind=target_kind,
            dirty=dirty,
        )

    def _default_branch(self, source_path: Path) -> str | None:
        result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            cwd=source_path,
            stream_output=False,
        )
        if result is None or result.exit_code != 0:
            return None
        return result.stdout.strip() or None

    def _head_commit(self, source_path: Path) -> str | None:
        result = self._run_git(
            ("rev-parse", "HEAD"), cwd=source_path, stream_output=False
        )
        if result is None or result.exit_code != 0:
            return None
        return result.stdout.strip() or None

    def _run_git(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        stream_output: bool,
    ) -> _GitCommandResult | None:
        self._check_stop()
        try:
            process = subprocess.Popen(
                (_GIT_PATH, *argv),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            self._error("git_command_failed", str(error))
            return None
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("git stdout/stderr pipes are required")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}
        try:
            while selector.get_map():
                if self.cancellation.is_set():
                    _terminate_process_group(process)
                    raise _GitCancelled
                if _deadline_expired(self.deadline_at):
                    _terminate_process_group(process)
                    self._error("operation_timeout", "Git operation timed out")
                    return None
                for key, _ in selector.select(timeout=0.05):
                    data = os.read(key.fd, _PROCESS_READ_CHUNK_BYTES)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    text = data.decode(errors="replace")
                    stream = key.data
                    chunks[stream].append(text)
                    if stream_output:
                        self.emit(stream, {"text": text}, False)
            exit_code = process.wait()
        finally:
            selector.close()
            if process.poll() is None:
                _terminate_process_group(process)
        return _GitCommandResult(
            exit_code=exit_code,
            stdout="".join(chunks["stdout"]),
            stderr="".join(chunks["stderr"]),
        )

    def _check_stop(self) -> None:
        if self.cancellation.is_set():
            raise _GitCancelled
        if _deadline_expired(self.deadline_at):
            self._error("operation_timeout", "Git operation timed out")
            raise _GitCancelled


def run_git_operation(
    *,
    request: GitRequest,
    workspace: Workspace,
    cancellation: threading.Event,
    deadline_at: datetime | None,
    emit: GitEventEmitter,
) -> None:
    """Execute one Git operation entirely inside the helper process."""
    _ContainedGitOperations(
        workspace=workspace,
        cancellation=cancellation,
        deadline_at=deadline_at,
        emit=emit,
    ).run(request)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_TERMINATE_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_KILL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return


def _deadline_expired(deadline_at: datetime | None) -> bool:
    return deadline_at is not None and datetime.now(UTC) >= deadline_at


def _git_command_error_message(result: _GitCommandResult) -> str:
    text = result.stderr.strip() or result.stdout.strip()
    return text or f"Git command failed with exit code {result.exit_code}"


def _registered_worktree(
    porcelain: str,
    *,
    worktree_path: Path,
) -> _GitWorktreeRegistration:
    for record in porcelain.split("\0\0"):
        fields = [field for field in record.split("\0") if field]
        if not fields or not fields[0].startswith("worktree "):
            continue
        registered_path = Path(fields[0].removeprefix("worktree "))
        if registered_path != worktree_path:
            continue
        branch_ref = next(
            (
                field.removeprefix("branch ")
                for field in fields[1:]
                if field.startswith("branch ")
            ),
            None,
        )
        branch_name = (
            branch_ref.removeprefix("refs/heads/")
            if branch_ref is not None and branch_ref.startswith("refs/heads/")
            else branch_ref
        )
        return _GitWorktreeRegistration(True, branch_name)
    return _GitWorktreeRegistration(False, None)


def _discovered_worktree(
    worktree_path: Path,
    *,
    registered: bool,
    repository_anchor_path: str,
    branch_name: str,
    failure_code: str,
    head_commit: str = "",
) -> _DiscoveredWorktree:
    fingerprint = hashlib.sha256(
        "\0".join(
            (
                str(worktree_path),
                repository_anchor_path,
                branch_name,
                head_commit,
                failure_code,
                str(registered),
            )
        ).encode()
    ).hexdigest()
    return _DiscoveredWorktree(
        worktree_path=worktree_path,
        registered=registered,
        repository_anchor_path=repository_anchor_path,
        branch_name=branch_name,
        fingerprint=fingerprint,
        failure_code=failure_code,
    )


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _git_ref_display_name(ref: str, short_name: str) -> str:
    if ref.startswith("refs/heads/"):
        return ref.removeprefix("refs/heads/")
    if ref.startswith("refs/remotes/"):
        return ref.removeprefix("refs/remotes/")
    if ref.startswith("refs/tags/"):
        return ref.removeprefix("refs/tags/")
    return short_name


def _git_ref_type(ref: str) -> str:
    if ref.startswith("refs/heads/"):
        return "branch"
    if ref.startswith("refs/remotes/"):
        return "remote_branch"
    if ref.startswith("refs/tags/"):
        return "tag"
    return "other"


def _git_ref_is_default(ref: str, short_name: str, default_branch: str | None) -> bool:
    if default_branch is None:
        return False
    return short_name == default_branch or ref == f"refs/heads/{default_branch}"
