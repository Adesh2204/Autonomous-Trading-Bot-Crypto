"""Fail-closed guards for write-capable PAR-only legacy entrypoints."""

from .base_exchange import ExchangeError

RETIRED_PAR_WRITE_ROUTE = "RETIRED_PAR_WRITE_ROUTE"


def reject_retired_par_write():
    """Stop a legacy PAR write route before credentials, network, or writes."""
    raise ExchangeError(RETIRED_PAR_WRITE_ROUTE)


def reject_retired_authorized_terminal_route():
    """Require the canonical two-asset gated launcher for any authorized run."""
    raise ExchangeError("RETIRED_AUTHORIZED_TERMINAL_ROUTE")


def reject_retired_scored_session_route():
    """Route approved sessions through the canonical two-asset launcher."""
    raise ExchangeError("RETIRED_SCORED_SESSION_ROUTE")
