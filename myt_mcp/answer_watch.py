"""Measures, never enforces, whether check_answer was called after compose_answer (27 Oct 2026: three chats in a row sent a retyped answer without calling it).

The server cannot see the message the assistant finally sends, so it cannot make anyone call check_answer, and a new refusal would only push the assistant to skip compose_answer too. This module only counts:
compose_answer notes the time, check_answer clears it, and when WAIT_SECONDS pass with no check_answer call one line is written to the log. It changes no answer and refuses nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("myt_mcp")
WAIT_SECONDS = 180
_PENDING: dict[str, float] = {}      # kind of answer -> when compose_answer returned it


def composed(kind: str) -> None:
    stamp = time.time()
    _PENDING[kind] = stamp
    try:
        asyncio.get_running_loop().call_later(WAIT_SECONDS, report, kind, stamp)
    except RuntimeError:       # no running loop (a plain call): nothing is scheduled, report() can still be called
        pass


def checked() -> None:
    """Any check_answer call clears every answer waiting: the assistant may name another kind than the one composed ('general')."""
    _PENDING.clear()


def report(kind: str, stamp: float) -> bool:
    """Writes the log line when this very answer is still unchecked; True when it did."""
    if _PENDING.get(kind) != stamp:
        return False
    _PENDING.pop(kind, None)
    log.info("CHECK check_answer was not called within %ss after compose_answer kind=%s: the operator may have received an answer that was retyped and never checked", WAIT_SECONDS, kind)
    return True
