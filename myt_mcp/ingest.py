"""Script answers that go from the operator's Chrome page straight to this server (decided 23 Oct 2026, the user chose it).

Why: claude.ai's browser tool shows the model only about the first 1,000 characters of a script's answer and marks the rest [TRUNCATED], so the model can never
hold a part whole, pass it "unchanged", or avoid re-typing it (seen on the LIS-PDL run: it rewrote the scripts, divided prices itself and typed the rows). So the script
POSTs its full result to /ingest/<token> on this server; the model only gets a short receipt and calls compose_answer(runs=[token]); the server reads the rows itself.

Safety: a token is made by the server for ONE recipe call (96 bits, not guessable), lives 3 hours, takes at most a few posts of at most 4 MB, and only for data of that
call: prices and flight/hotel/activity facts read from a page the operator opened. Nothing else is read from the page and nothing is sent anywhere else.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

TTL_SECONDS = 3 * 3600
MAX_BODY = 4_000_000
MAX_POSTS = 5
MAX_PENDING = 400


@dataclass
class Run:
    site: str
    wishes: dict[str, Any]
    filters_used: list[str]
    created: float = field(default_factory=time.time)
    result: str | None = None
    posts: int = 0
    url: str = ""
    received_at: float | None = None


class IngestStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def _sweep(self) -> None:
        now = time.time()
        for token in [t for t, r in self._runs.items() if now - r.created > TTL_SECONDS]:
            del self._runs[token]
        while len(self._runs) > MAX_PENDING:
            del self._runs[min(self._runs, key=lambda t: self._runs[t].created)]

    def new_run(self, site: str, wishes: dict[str, Any], filters_used: list[str] | None = None) -> str:
        self._sweep()
        token = secrets.token_urlsafe(12)
        self._runs[token] = Run(site, wishes or {}, list(filters_used or []))
        return token

    def clear(self) -> None:
        self._runs.clear()

    def issued(self, since: float) -> list[Run]:
        """Runs a recipe call issued after `since` (wall-clock seconds), oldest first."""
        self._sweep()
        return sorted((r for r in self._runs.values() if r.created > since), key=lambda r: r.created)

    def accept(self, token: str, body: bytes) -> tuple[int, dict[str, Any]]:
        """-> (http status, receipt). The body is the script's whole answer as JSON text."""
        self._sweep()
        run = self._runs.get(token)
        if run is None:
            return 404, {"ok": False, "error": "unknown or expired run"}
        if len(body) > MAX_BODY:
            return 413, {"ok": False, "error": "answer too large"}
        if run.posts >= MAX_POSTS:
            return 429, {"ok": False, "error": "this run already received its answers"}
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return 400, {"ok": False, "error": "not JSON"}
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "not a JSON object"}
        run.posts += 1
        run.result, run.received_at = json.dumps(data, ensure_ascii=False), time.time()
        run.url = str(data.get("page_url") or "")[:600]
        rows = data.get("rows")
        return 200, {"ok": True, "rows": len(rows) if isinstance(rows, list) else None, "chars": len(body)}

    def items(self, tokens: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """-> (site_results items for convert_all, problems). Each item carries the wishes and filters the server itself issued with the recipe."""
        self._sweep()
        items, problems = [], []
        for token in dict.fromkeys(tokens):
            run = self._runs.get(token)
            if run is None:
                problems.append(f"run {token}: unknown or expired (runs live 3 hours): run the recipe again")
            elif run.result is None:
                problems.append(f"run {token} ({run.site}): no answer arrived from the page. Run the script again in the same Chrome tab; if its receipt says received=false, tell the operator that this source could not be read (a block or a closed tab)")
            else:
                items.append({"site": run.site, "result": run.result, "url": run.url, "wishes": run.wishes, "filters_used": run.filters_used})
        return items, problems


STORE = IngestStore()
