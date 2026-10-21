"""The operators' playbook (instructions/claude_project.md), served to Claude by the MCP server itself.

Claude clients shorten long server instructions, so the server sends short core rules (app.INSTRUCTIONS) and
Claude fetches the detailed section it needs with the quote_guide tool. The Markdown file stays the one place
where the playbook is written.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

GUIDE_FILE = Path(__file__).resolve().parent.parent / "instructions" / "claude_project.md"

# topic -> start of the section heading in the playbook
TOPICS = {
    "workflow": "Workflow",
    "capabilities": "What this connector can and cannot do",
    "cost_lines": "How to fill a cost line",
    "myt_filling": "Writing the quote into MYT",
    "reservations": "Supplier reservations, vouchers and reconciliation",
    "cars": "Car rentals",
    "website_rules": "Rules for collecting prices from websites",
    "trains": "Trains in Italy",
    "flights": "Flights",
    "lounges": "Airport lounges",
    "hotels": "Hotels",
    "filters": "Filters: hotels",
    "transfers": "Transfers",
    "other_sources": "Sources not built yet",
    "activities": "Activities",
    "versions": "Comparing quotation versions",
    "correct_data": "Correct, real data",
    "source_data": "What to read from each source",
    "comparison": "Comparison checklist",
    "answer_format": "Answer format",
    "rules": "Rules",
}


@lru_cache(maxsize=1)
def sections() -> dict[str, str]:
    """topic -> that section's Markdown (heading included)."""
    text = GUIDE_FILE.read_text(encoding="utf-8")
    blocks = {b.split("\n", 1)[0].strip(): "## " + b.strip() for b in text.split("\n## ")[1:]}   # title -> section
    found = {}
    for topic, heading in TOPICS.items():
        # an exact title wins ("Rules"), otherwise EVERY title that starts with it, in file order: "Flights" serves SATA,
        # El Al, Skyscanner and the comparison table, not only the first "Flights: ..." section
        titles = [heading] if heading in blocks else [t for t in blocks if t.startswith(heading)]
        if titles:
            found[topic] = "\n\n".join(blocks[t] for t in titles)
    return found
