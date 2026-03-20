"""Runtime execution error hierarchy.

All errors raised by RuntimeAdapter.execute() implementations belong here.
The chassis catches these to drive coherent lifecycle transitions.
"""


class RuntimeExecutionError(Exception):
    """Base class for all runtime adapter execution errors."""


class UnsupportedCapabilityError(RuntimeExecutionError):
    """Capability is not supported by this adapter.

    Raised by execute() when the requested capability is outside the adapter's
    explicit scope. Chassis maps this to a 'rejected' terminal status.
    """


class RuntimeInvocationError(RuntimeExecutionError):
    """Runtime subprocess or HTTP call failed to complete.

    Raised when the underlying runtime process could not be invoked
    (non-zero exit, connection refused, etc.). Distinct from timeout.
    """


class RuntimeTimeoutError(RuntimeExecutionError):
    """Runtime invocation exceeded the configured timeout.

    Chassis maps this to a 'timed_out' terminal status in the result dict,
    while the lifecycle state transitions to 'failed'.
    """


class RuntimeContractError(RuntimeExecutionError):
    """Runtime returned output that cannot be normalized to RuntimeExecutionResult.

    Raised when raw output is malformed, unparseable, or structurally invalid.
    Chassis maps this to a 'failed' terminal state.
    """
