"""Prepare the Agent-child seccomp filter and execute trusted bubblewrap."""

import ctypes
import errno
import os
import sys
from typing import NoReturn

_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000
_SCMP_CMP_MASKED_EQ = 7
_CLONE_NEWUSER = 0x10000000
_BWRAP_PATH = "/opt/azents-runtime/bin/bwrap"


class _ScmpArgCompare(ctypes.Structure):
    """libseccomp syscall argument comparison."""

    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def _seccomp_error(error_number: int) -> int:
    return _SCMP_ACT_ERRNO | error_number


def _add_rule(
    library: ctypes.CDLL,
    context: int,
    *,
    syscall_name: str,
    action: int,
    comparison: _ScmpArgCompare | None = None,
) -> None:
    syscall_number = library.seccomp_syscall_resolve_name(syscall_name.encode())
    if syscall_number < 0:
        return
    comparison_pointer = None if comparison is None else ctypes.pointer(comparison)
    result = library.seccomp_rule_add_array(
        context,
        action,
        syscall_number,
        0 if comparison is None else 1,
        comparison_pointer,
    )
    if result != 0:
        raise OSError(-result, f"cannot add seccomp rule for {syscall_name}")


def _seccomp_program_fd() -> int:
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_ScmpArgCompare),
    ]
    library.seccomp_rule_add_array.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_export_bpf.restype = ctypes.c_int

    context = library.seccomp_init(_SCMP_ACT_ALLOW)
    if context is None:
        raise RuntimeError("cannot initialize Agent-child seccomp filter")
    try:
        user_namespace = _ScmpArgCompare(
            arg=0,
            op=_SCMP_CMP_MASKED_EQ,
            datum_a=_CLONE_NEWUSER,
            datum_b=_CLONE_NEWUSER,
        )
        _add_rule(
            library,
            context,
            syscall_name="unshare",
            action=_seccomp_error(errno.EPERM),
            comparison=user_namespace,
        )
        _add_rule(
            library,
            context,
            syscall_name="clone",
            action=_seccomp_error(errno.EPERM),
            comparison=user_namespace,
        )
        _add_rule(
            library,
            context,
            syscall_name="clone3",
            action=_seccomp_error(errno.ENOSYS),
        )
        _add_rule(
            library,
            context,
            syscall_name="setns",
            action=_seccomp_error(errno.EPERM),
        )
        descriptor = os.memfd_create(
            "azents-agent-userns-seccomp",
            os.MFD_CLOEXEC,
        )
        result = library.seccomp_export_bpf(context, descriptor)
        if result != 0:
            os.close(descriptor)
            raise OSError(-result, "cannot export Agent-child seccomp filter")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    finally:
        library.seccomp_release(context)


def _bwrap_arguments(arguments: list[str], seccomp_fd: int) -> list[str]:
    try:
        command_separator = arguments.index("--")
    except ValueError as error:
        raise RuntimeError("bubblewrap command separator is missing") from error
    return [
        *arguments[:command_separator],
        "--seccomp",
        str(seccomp_fd),
        *arguments[command_separator:],
    ]


def main() -> NoReturn:
    """Execute bubblewrap with a filter denying Agent-created user namespaces."""
    if os.getuid() == 0 or os.getgid() == 0:
        raise RuntimeError("bubblewrap launcher requires a non-root Runner")
    arguments = sys.argv[1:]
    if not arguments or arguments[0] != _BWRAP_PATH:
        raise RuntimeError("bubblewrap launcher received an invalid executable")
    descriptor = _seccomp_program_fd()
    os.set_inheritable(descriptor, True)
    os.execv(arguments[0], _bwrap_arguments(arguments, descriptor))


if __name__ == "__main__":
    main()
