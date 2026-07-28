"""Pure Runtime transfer transition policy."""

from azents.runtime.transfer.data import RuntimeTransferDirection, RuntimeTransferPhase


def phase_transition_allowed(
    direction: RuntimeTransferDirection,
    current: RuntimeTransferPhase,
    target: RuntimeTransferPhase,
) -> bool:
    """Return whether one non-terminal transition is valid for a direction."""
    if target is RuntimeTransferPhase.TERMINAL:
        return current is not RuntimeTransferPhase.TERMINAL
    match direction:
        case RuntimeTransferDirection.DOWNLOAD:
            return (current, target) in {
                (RuntimeTransferPhase.PREPARING, RuntimeTransferPhase.READY),
                (RuntimeTransferPhase.READY, RuntimeTransferPhase.STREAMING),
                (RuntimeTransferPhase.STREAMING, RuntimeTransferPhase.VERIFYING),
                (RuntimeTransferPhase.VERIFYING, RuntimeTransferPhase.COMMITTED),
            }
        case RuntimeTransferDirection.UPLOAD:
            return (current, target) in {
                (RuntimeTransferPhase.PREPARING, RuntimeTransferPhase.READY),
                (RuntimeTransferPhase.READY, RuntimeTransferPhase.STREAMING),
                (RuntimeTransferPhase.STREAMING, RuntimeTransferPhase.VERIFYING),
                (RuntimeTransferPhase.VERIFYING, RuntimeTransferPhase.AVAILABLE),
                (RuntimeTransferPhase.AVAILABLE, RuntimeTransferPhase.CONSUMING),
                (RuntimeTransferPhase.CONSUMING, RuntimeTransferPhase.CONSUMED),
            }
