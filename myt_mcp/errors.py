"""One place that decides what a failing tool tells the model, so no failure crashes the server."""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

log = logging.getLogger("myt_mcp")
P = ParamSpec("P")
R = TypeVar("R")


class IntegrationError(Exception):
    """An anticipated failure in an outside system (MYT, Ofran...). The message is written for the
    operator and is passed to the model as is."""


def tool_errors(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap a tool so that:
    - ToolError and IntegrationError reach the model with their own message;
    - anything unexpected is logged with its traceback, and the model gets a short, safe message
      instead of the SDK's bare "Error executing tool"."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.monotonic()      # one line per tool call (name, outcome, seconds; never the arguments) so a chat can be traced
        try:
            result = await fn(*args, **kwargs)
            log.info("TOOL %s ok %.1fs", fn.__name__, time.monotonic() - started)
            return result
        except ToolError:
            log.info("TOOL %s refused %.1fs", fn.__name__, time.monotonic() - started)
            raise
        except IntegrationError as e:
            log.info("TOOL %s source error %.1fs", fn.__name__, time.monotonic() - started)
            raise ToolError(str(e)) from e
        except Exception as e:
            log.exception("Unexpected error in tool %s", fn.__name__)
            raise ToolError(
                f"{fn.__name__} failed unexpectedly ({type(e).__name__}). Nothing was changed. "
                "Try once more; if it fails again, tell the developer (details are in the server log)."
            ) from e

    return wrapper
